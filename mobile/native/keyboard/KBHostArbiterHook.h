//
//  KBHostArbiterHook.h
//  KeyboardHostBundleID
//
//  iOS 26.4+ host-app Bundle ID capture via _UIKeyboardArbiterClient swizzle.
//
//  Rationale for ObjC + +load (not Swift):
//  - +load runs at dyld image-load time, strictly before any Swift runtime
//    initialization and before UIKit's first keyboard-arbiter dispatch.
//  - Installing the swizzle any later risks missing the initial destination
//    change that carries the host bundle identifier.
//

#import <Foundation/Foundation.h>
@class UIInputViewController;

NS_ASSUME_NONNULL_BEGIN

/// Captures the host app's Bundle ID from inside a keyboard extension on
/// iOS 26.4+ by swizzling the private `_UIKeyboardArbiterClientInputDestination`
/// `queue_keyboardChanged:onComplete:` callback.
/// Also captures direct `_didHandleKeyboardClientChange:` delivery on current
/// UIKit. Each selector's complete argument/return signature is checked first.
///
/// The hook installs automatically via `+load` when the extension loads on
/// iOS 26.4 or later. On earlier iOS versions the hook is a no-op and callers
/// should fall back to the legacy PKService path (see `LegacyHostResolver`).
/// Installation retries when a query initializes a lazily loaded UIKit class.
@interface KBHostArbiterHook : NSObject

/// Returns the most recent host Bundle ID observed by the swizzle in the
/// current process, or `nil` if the hook has not fired yet (or is disabled
/// because the running iOS is < 26.4).
///
/// Thread-safe.
/// Historical observation only; this does not confirm the current host.
+ (nullable NSString *)lastCapturedHostBundleId;

/// Snapshot before pinging the arbiter. Each destination event (including
/// invalid/empty events) or explicit invalidation advances this generation.
+ (uint64_t)captureGeneration;

/// Atomically returns a valid capture only if an event was observed after
/// the supplied generation. Explicit invalidation cancels older queries even
/// if another valid event follows. An invalid latest event also returns nil.
+ (nullable NSString *)hostBundleIdCapturedAfterGeneration:(uint64_t)generation
    NS_SWIFT_NAME(hostBundleId(capturedAfter:));

/// Clears the last observation, for example when the keyboard disappears.
+ (void)invalidateCache;

/// Asks the keyboard arbiter to check its connection. This may trigger a
/// destination callback, but does not guarantee one. Never treat a previous
/// cached value as confirmation that this request succeeded.
///
/// No-op on iOS < 26.4.
+ (void)activeArbiterCheck;

/// Fresh host lookup for iOS versions before 26.4. No process-wide cache.
/// Private PKService/XPC compatibility path; exceptions and missing APIs return nil.
+ (nullable NSString *)legacyHostBundleIDForController:(UIInputViewController *)controller
    NS_SWIFT_NAME(legacyHostBundleID(for:));

@end

NS_ASSUME_NONNULL_END
