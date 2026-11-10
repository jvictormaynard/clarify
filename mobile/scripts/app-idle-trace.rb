# Isolated observation lab. Never merge this file into the product branch.
module AppIdleTrace
  def self.replace_once(source, boundary, replacement)
    raise "Idle trace boundary changed: #{boundary.inspect}" unless source.scan(boundary).length == 1
    source.sub(boundary, replacement)
  end

  def self.delegate(source)
    boundary = /didFinishLaunchingWithOptions[^\{]+\{\n/
    replace_once(source, boundary, source.match(boundary).to_s + "    ClarifyAppIdleTrace.start()\n")
  end

  def self.cloud(source)
    boundary = '    else { (data, response) = try await session.data(for: request) }'
    raise 'Expected two original CloudAccount session boundaries' unless source.scan(boundary).length == 2
    replacement = <<~'SWIFT'
        else {
          do { (data, response) = try await session.data(for: request) }
          catch {
            let failure = error as NSError
            let underlying = failure.userInfo[NSUnderlyingErrorKey] as? NSError
            NSLog("ClarifyAppIdleError uptime=%.6f catalog=%d domain=%@ code=%ld underlyingDomain=%@ underlyingCode=%ld",
              ProcessInfo.processInfo.systemUptime, path == "/v1/text-actions" ? 1 : 0,
              String(failure.domain.prefix(120)), failure.code,
              String((underlying?.domain ?? "none").prefix(120)), underlying?.code ?? 0)
            throw error
          }
        }
    SWIFT
    source.gsub(boundary, replacement.lines.map { |line| '    ' + line }.join.rstrip)
  end

  def self.observer
    <<~'SWIFT'
      import UIKit
      import QuartzCore

      @MainActor final class ClarifyAppIdleTrace: NSObject {
        private static var instance: ClarifyAppIdleTrace?
        private var timer: Timer?
        private var deadline: TimeInterval = 0
        private let started = ProcessInfo.processInfo.systemUptime
        private var records = 0
        private var limited = false
        private var previousAnimations: [String] = []
        static func start() {
          guard instance == nil else { return }
          let trace = ClarifyAppIdleTrace(); instance = trace
          for name in [UIResponder.keyboardWillShowNotification, UIResponder.keyboardDidShowNotification,
            UIResponder.keyboardWillHideNotification, UIResponder.keyboardDidHideNotification,
            UIResponder.keyboardWillChangeFrameNotification, UIResponder.keyboardDidChangeFrameNotification] {
            NotificationCenter.default.addObserver(trace, selector: #selector(trace.keyboard(_:)), name: name, object: nil)
          }
          trace.log("stage=start")
        }
        private func log(_ message: String) {
          guard !limited else { return }
          guard records < 4096, ProcessInfo.processInfo.systemUptime - started < 1800 else {
            limit(); return
          }
          records += 1
          NSLog("ClarifyAppIdleTrace pid=%d uptime=%.6f %@", ProcessInfo.processInfo.processIdentifier,
            ProcessInfo.processInfo.systemUptime, message)
        }
        private func limit() {
          guard !limited else { return }; limited = true
          NSLog("ClarifyAppIdleTrace pid=%d uptime=%.6f stage=trace-limit records=%d", ProcessInfo.processInfo.processIdentifier,
            ProcessInfo.processInfo.systemUptime, records)
        }
        @objc private func keyboard(_ notification: Notification) {
          let info = notification.userInfo ?? [:]
          let frame = (info[UIResponder.keyboardFrameEndUserInfoKey] as? NSValue)?.cgRectValue ?? .zero
          log("stage=keyboard name=\(notification.name.rawValue) duration=\(info[UIResponder.keyboardAnimationDurationUserInfoKey] as? Double ?? -1) frame=\(frame)")
          snapshot("notification")
          if notification.name == UIResponder.keyboardWillHideNotification || notification.name == UIResponder.keyboardDidHideNotification {
            deadline = ProcessInfo.processInfo.systemUptime + 75
            if timer == nil {
              let next = Timer(timeInterval: 1, target: self, selector: #selector(sample), userInfo: nil, repeats: true)
              timer = next; RunLoop.main.add(next, forMode: .common)
            }
          }
        }
        @objc private func sample() {
          guard ProcessInfo.processInfo.systemUptime <= deadline,
            ProcessInfo.processInfo.systemUptime - started < 1800, records < 4046 else {
            timer?.invalidate(); timer = nil
            if records >= 4046 || ProcessInfo.processInfo.systemUptime - started >= 1800 { limit() }
            else { log("stage=sample-end") }
            return
          }
          snapshot("post-hide")
        }
        private func snapshot(_ reason: String) {
          let windows = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.flatMap { $0.windows }
          var seen = Set<ObjectIdentifier>(); var animations = 0
          var details: [String] = []
          @MainActor func visit(_ layer: CALayer, _ path: String) {
            guard seen.count < 2048, seen.insert(ObjectIdentifier(layer)).inserted else { return }
            for key in (layer.animationKeys() ?? []).prefix(16) {
              guard animations < 48, let animation = layer.animation(forKey: key) else { break }
              animations += 1
              let owner = (layer.delegate as? UIView).map { String(describing: type(of: $0)) } ?? "none"
              details.append("path=\(path) owner=\(owner) layer=\(type(of: layer)) key=\(key.prefix(100)) duration=\(animation.duration) begin=\(animation.beginTime) repeats=\(animation.repeatCount) speed=\(animation.speed) hidden=\(layer.isHidden) frame=\(layer.frame)")
            }
            for (index, child) in (layer.sublayers ?? []).enumerated() { visit(child, path + ".\(index)") }
          }
          for (index, window) in windows.enumerated() { visit(window.layer, "w\(index)") }
          if details != previousAnimations {
            for detail in details { log("stage=animation reason=\(reason) " + detail) }
            previousAnimations = details
          }
          log("stage=snapshot reason=\(reason) windows=\(windows.count) visited=\(seen.count) animations=\(animations) capped=\(seen.count >= 2048 || animations >= 48)")
        }
      }
    SWIFT
  end
end
