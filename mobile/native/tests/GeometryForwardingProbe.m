// Diagnostic fixture only. Observe geometry sent across the extension boundary.
// Do not change arguments or record document content.
#import <UIKit/UIKit.h>
#import <objc/runtime.h>
#import <objc/message.h>
#import <string.h>
#import <stdatomic.h>

static IMP queueForward;
static IMP targetedForward;
static IMP distantForward;
static _Atomic(NSUInteger) geometryEvents;

static void LogGeometry(NSInvocation *invocation, NSString *kind) {
  NSString *name = NSStringFromSelector(invocation.selector);
  NSString *lower = name.lowercaseString;
  if (![lower containsString:@"size"] && ![lower containsString:@"intrinsic"] && ![lower containsString:@"frame"]) return;
  if (atomic_fetch_add(&geometryEvents, 1) >= 120) return;
  NSMutableArray *values = [NSMutableArray array];
  NSMethodSignature *signature = invocation.methodSignature;
  for (NSUInteger index = 2; index < signature.numberOfArguments; index++) {
    const char *type = [signature getArgumentTypeAtIndex:index];
    if (strncmp(type, "{CGSize=", 8) == 0) {
      CGSize size; [invocation getArgument:&size atIndex:index];
      [values addObject:NSStringFromCGSize(size)];
    } else if (strncmp(type, "{CGRect=", 8) == 0) {
      CGRect frame; [invocation getArgument:&frame atIndex:index];
      [values addObject:NSStringFromCGRect(frame)];
    }
  }
  NSLog(@"ClarifyGeometryIPC %@ %@ %@", kind, name, values);
  if (values.count) NSLog(@"ClarifyGeometryIPCStack %@", [[NSThread callStackSymbols] componentsJoinedByString:@" | "]);
}
static void QueueForward(id self, SEL command, NSInvocation *invocation) {
  LogGeometry(invocation, @"queue"); ((void (*)(id, SEL, id))queueForward)(self, command, invocation);
}
static void TargetedForward(id self, SEL command, NSInvocation *invocation) {
  LogGeometry(invocation, @"targeted"); ((void (*)(id, SEL, id))targetedForward)(self, command, invocation);
}
static void DistantForward(id self, SEL command, NSInvocation *invocation) {
  LogGeometry(invocation, @"distant"); ((void (*)(id, SEL, id))distantForward)(self, command, invocation);
}
static void Install(NSString *name, IMP replacement, IMP *original) {
  Class cls = NSClassFromString(name);
  SEL selector = @selector(forwardInvocation:);
  Method method = cls ? class_getInstanceMethod(cls, selector) : NULL;
  if (!method) { NSLog(@"ClarifyGeometryHook missing %@", name); return; }
  *original = method_getImplementation(method);
  // Keep inherited implementations on their original class.
  if (!class_addMethod(cls, selector, replacement, method_getTypeEncoding(method))) method_setImplementation(method, replacement);
  NSLog(@"ClarifyGeometryHook installed %@", name);
}
void ClarifyGeometryLogController(UIInputViewController *controller, NSString *phase) {
  for (id object in @[controller, controller.parentViewController ?: NSNull.null]) {
    for (NSString *name in @[@"_autosizeToCurrentKeyboard", @"_alignsToContentViewController", @"_disableAutomaticKeyboardBehavior"]) {
      SEL selector = NSSelectorFromString(name);
      NSMethodSignature *signature = [object methodSignatureForSelector:selector];
      if (signature.numberOfArguments != 2 || (strcmp(signature.methodReturnType, "B") && strcmp(signature.methodReturnType, "c"))) continue;
      BOOL value = ((BOOL (*)(id, SEL))objc_msgSend)(object, selector);
      NSLog(@"ClarifyGeometryFlag %@ %@ %@=%d", phase, NSStringFromClass([object class]), name, value);
    }
  }
}
@interface ClarifyGeometryForwardingProbe : NSObject @end
@implementation ClarifyGeometryForwardingProbe
+ (void)load {
  Install(@"_UIQueueingProxy", (IMP)QueueForward, &queueForward);
  Install(@"_UITargetedProxy", (IMP)TargetedForward, &targetedForward);
  Install(@"_NSXPCDistantObject", (IMP)DistantForward, &distantForward);
}
@end
