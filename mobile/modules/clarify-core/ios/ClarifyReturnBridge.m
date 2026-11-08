#import "ClarifyReturnBridge.h"
#import <UIKit/UIKit.h>
#import <objc/runtime.h>
#import <objc/message.h>
#import <string.h>

static BOOL Matches(id receiver, SEL selector, NSUInteger arguments, BOOL objectResult) {
  if (![receiver respondsToSelector:selector]) return NO;
  NSMethodSignature *signature = [receiver methodSignatureForSelector:selector];
  if (!signature || signature.numberOfArguments != arguments) return NO;
  const char *result = signature.methodReturnType;
  return objectResult ? result[0] == '@' : (strcmp(result, "B") == 0 || strcmp(result, "c") == 0);
}

// Experimental, user-authorized TestFlight behavior. These private selectors
// remain explicit. Missing methods, changed signatures and exceptions fail closed.
@implementation ClarifyReturnBridge
+ (BOOL)openSourceBundleID:(NSString *)bundleID {
  if (![NSThread isMainThread] || UIApplication.sharedApplication.applicationState != UIApplicationStateActive) return NO;
  @try {
    if ([bundleID isEqualToString:NSBundle.mainBundle.bundleIdentifier]
        || [bundleID hasPrefix:[NSBundle.mainBundle.bundleIdentifier stringByAppendingString:@"."]]) return NO;
    if (bundleID.length > 0) {
      Class cls = NSClassFromString(@"LSApplicationWorkspace");
      SEL getter = NSSelectorFromString(@"defaultWorkspace");
      if (cls && Matches(cls, getter, 2, YES)) {
        id workspace = ((id (*)(id, SEL))objc_msgSend)(cls, getter);
        SEL open = NSSelectorFromString(@"openApplicationWithBundleID:");
        if (Matches(workspace, open, 3, NO)) {
          if (((BOOL (*)(id, SEL, id))objc_msgSend)(workspace, open, bundleID)) return YES;
        }
      }
    }
    // Breadcrumb fallback for a fresh keyboard activation when host lookup fails.
    UIApplication *app = UIApplication.sharedApplication;
    Ivar ivar = class_getInstanceVariable([UIApplication class], "_systemNavigationAction");
    id action = ivar ? object_getIvar(app, ivar) : nil;
    SEL destinationsSelector = NSSelectorFromString(@"destinations");
    SEL send = NSSelectorFromString(@"sendResponseForDestination:");
    if (!action || !Matches(action, destinationsSelector, 2, YES) || !Matches(action, send, 3, NO)) return NO;
    const char *argument = [[action methodSignatureForSelector:send] getArgumentTypeAtIndex:2];
    if (strcmp(argument, @encode(NSUInteger)) != 0) return NO;
    id destinations = ((id (*)(id, SEL))objc_msgSend)(action, destinationsSelector);
    if (![destinations isKindOfClass:NSArray.class]) return NO;
    NSNumber *destination = [destinations firstObject];
    if (![destination isKindOfClass:NSNumber.class]) return NO;
    return ((BOOL (*)(id, SEL, NSUInteger))objc_msgSend)(action, send, destination.unsignedIntegerValue);
  } @catch (__unused NSException *error) { return NO; }
}
@end
