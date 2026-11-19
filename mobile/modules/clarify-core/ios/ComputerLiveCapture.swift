import Foundation
import CryptoKit

// The tap supplies owned PCM bytes. This queue has no microphone or network work.
final class ComputerLiveCapture {
  private let lock = NSLock()
  private var frames: [Data] = []
  private var pending = 0
  private var total = 0
  private var digest = SHA256()
  private var ended = false
  private var failure: Error?
  private var worker: Task<ComputerResult, Error>?
  func append(_ pcm: Data) throws {
    lock.lock(); defer { lock.unlock() }
    if let failure { throw failure }
    guard !ended, !pcm.isEmpty, pcm.count % 2 == 0, pcm.count <= 2560,
      pending + pcm.count <= 256000, total + pcm.count <= 9600000 else {
      failure = ComputerFailure.invalidAudio; frames.removeAll(); throw ComputerFailure.invalidAudio
    }
    frames.append(pcm); pending += pcm.count; total += pcm.count; digest.update(data: pcm)
  }
  func end() { lock.lock(); ended = true; lock.unlock() }
  func cancel() {
    lock.lock(); failure = CancellationError(); ended = true; frames.removeAll(); pending = 0
    let task = worker; lock.unlock(); task?.cancel()
  }
  private func next() throws -> ([Data], Bool, Int, String) {
    lock.lock(); defer { lock.unlock() }
    if let failure { throw failure }
    let batch = Array(frames.prefix(8)); frames.removeFirst(batch.count)
    var snapshot = digest
    let hash = ended && batch.isEmpty ? snapshot.finalize().map { String(format: "%02x", $0) }.joined() : ""
    return (batch, ended, total, hash)
  }
  private func acknowledge(_ count: Int) { lock.lock(); pending -= count; lock.unlock() }
  @MainActor func start(admit: @escaping () async throws -> Void,
    feed: @escaping (Int, [Data]) async throws -> Void,
    finish: @escaping (Int, String) async throws -> ComputerResult,
    abort: @escaping () -> Void) {
    let task = Task { @MainActor in
      do {
        try Task.checkCancellation()
        try await admit()
        var sequence = 0
        while true {
          try Task.checkCancellation()
          let (batch, ended, bytes, hash) = try self.next()
          if !batch.isEmpty {
            try await feed(sequence, batch); self.acknowledge(batch.reduce(0) { $0 + $1.count }); sequence += batch.count
          } else if ended { return try await finish(bytes, hash) }
          else { try await Task.sleep(nanoseconds: 10_000_000) }
        }
      } catch { abort(); throw error }
    }
    lock.lock(); worker = task; let cancelled = failure != nil; lock.unlock()
    if cancelled { task.cancel() }
  }
  @MainActor func result() async throws -> ComputerResult {
    guard let worker else { throw ComputerFailure.notReady }
    return try await worker.value
  }
}
