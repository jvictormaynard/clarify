// Diagnostic fixture only. Compare isolated geometry interventions.
// Never compile into the product. Do not record document content.
#import <UIKit/UIKit.h>
#import <objc/runtime.h>
#import <objc/message.h>
#import <string.h>
#import <stdatomic.h>
#import "GeometryConfig.h"

static IMP queueForward;
static IMP targetedForward;
static IMP distantForward;
static _Atomic(NSUInteger) geometryEvents;
static IMP automaticBehavior;
static IMP nativeAutosize;
static IMP contentAlignment;
static IMP operatorFitting;
static IMP operatorPreferred;
static IMP operatorPresentation;

NSString *ClarifyGeometryVariant(void) {
  return [NSString stringWithContentsOfFile:CLARIFY_GEOMETRY_CONFIG encoding:NSUTF8StringEncoding error:nil] ?: @"baseline";
}
static BOOL AutomaticBehavior(id self, SEL command) {
  if ([ClarifyGeometryVariant() isEqualToString:@"operator-no-auto"]) return YES;
  return ((BOOL (*)(id, SEL))automaticBehavior)(self, command);
}
static BOOL NativeAutosize(id self, SEL command) {
  if ([ClarifyGeometryVariant() isEqualToString:@"native-autosize"]) return YES;
  return ((BOOL (*)(id, SEL))nativeAutosize)(self, command);
}
static BOOL ContentAlignment(id self, SEL command) {
  if ([ClarifyGeometryVariant() isEqualToString:@"align-content"]) return YES;
  return ((BOOL (*)(id, SEL))contentAlignment)(self, command);
}
static CGSize OperatorFitting(id self, SEL command, CGSize size, float horizontal, float vertical) {
  if ([ClarifyGeometryVariant() isEqualToString:@"operator-fitting"]) return CGSizeMake(size.width, 216);
  return ((CGSize (*)(id, SEL, CGSize, float, float))operatorFitting)(self, command, size, horizontal, vertical);
}
static CGSize OperatorPreferred(id self, SEL command) {
  if ([ClarifyGeometryVariant() isEqualToString:@"operator-preferred"]) return CGSizeMake(402, 216);
  return ((CGSize (*)(id, SEL))operatorPreferred)(self, command);
}
static UIModalPresentationStyle OperatorPresentation(id self, SEL command) {
  if ([ClarifyGeometryVariant() isEqualToString:@"operator-fullscreen"]) return UIModalPresentationFullScreen;
  return ((UIModalPresentationStyle (*)(id, SEL))operatorPresentation)(self, command);
}
void ClarifyGeometryConfigure(UIInputViewController *controller) {
  NSString *variant = ClarifyGeometryVariant();
  id target = nil; SEL selector = nil;
  if ([variant isEqualToString:@"native-autosize"]) {
    target = controller; selector = NSSelectorFromString(@"_setAutosizeToCurrentKeyboard:");
  } else if ([variant isEqualToString:@"align-content"]) {
    target = controller; selector = NSSelectorFromString(@"set_alignsToContentViewController:");
  } else if ([variant isEqualToString:@"operator-no-auto"]) {
    target = controller.parentViewController; selector = NSSelectorFromString(@"__hostDisablesAutomaticKeyboardBehavior:");
  }
  if (target && selector && [target respondsToSelector:selector]) ((void (*)(id, SEL, BOOL))objc_msgSend)(target, selector, YES);
}

static void LogGeometry(NSInvocation *invocation, NSString *kind) {
  NSString *name = NSStringFromSelector(invocation.selector);
  NSString *lower = name.lowercaseString;
  if (![lower containsString:@"size"] && ![lower containsString:@"intrinsic"] && ![lower containsString:@"frame"]) return;
  if (atomic_fetch_add(&geometryEvents, 1) >= 800) return;
  NSMutableArray *values = [NSMutableArray array];
  NSMethodSignature *signature = invocation.methodSignature;
  for (NSUInteger index = 2; index < signature.numberOfArguments; index++) {
    const char *type = [signature getArgumentTypeAtIndex:index];
    if (strncmp(type, "{CGSize=", 8) == 0) {
      CGSize size; [invocation getArgument:&size atIndex:index];
      if ([ClarifyGeometryVariant() isEqualToString:@"incoming-size"] && [name hasPrefix:@"__setContentSize:"]) {
        size.height = 216; [invocation setArgument:&size atIndex:index];
      }
      [values addObject:NSStringFromCGSize(size)];
    } else if (strncmp(type, "{CGRect=", 8) == 0) {
      CGRect frame; [invocation getArgument:&frame atIndex:index];
      [values addObject:NSStringFromCGRect(frame)];
    }
  }
  NSLog(@"ClarifyGeometryIPC %@ %@ %@ %@", ClarifyGeometryVariant(), kind, name, [values componentsJoinedByString:@","]);
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
static void InstallSelector(NSString *name, SEL selector, IMP replacement, IMP *original) {
  Class cls = NSClassFromString(name);
  Method method = cls ? class_getInstanceMethod(cls, selector) : NULL;
  if (!method) { NSLog(@"ClarifyGeometryHook missing %@", name); return; }
  *original = method_getImplementation(method);
  // Keep inherited implementations on their original class.
  if (!class_addMethod(cls, selector, replacement, method_getTypeEncoding(method))) method_setImplementation(method, replacement);
  NSLog(@"ClarifyGeometryHook installed %@", name);
}
void ClarifyGeometryLogController(UIInputViewController *controller, NSString *phase) {
  for (id object in @[controller, controller.parentViewController ?: NSNull.null]) {
    for (NSString *name in @[@"_remoteViewControllerProxyToOperator", @"_remoteViewControllerProxyToViewController"]) {
      Ivar ivar = class_getInstanceVariable([object class], name.UTF8String);
      if (ivar) {
        id proxy = object_getIvar(object, ivar);
        NSLog(@"ClarifyGeometryProxy %@ %@", name, NSStringFromClass(object_getClass(proxy)));
      }
    }
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
  InstallSelector(@"_UIQueueingProxy", @selector(forwardInvocation:), (IMP)QueueForward, &queueForward);
  InstallSelector(@"_UITargetedProxy", @selector(forwardInvocation:), (IMP)TargetedForward, &targetedForward);
  InstallSelector(@"_NSXPCDistantObject", @selector(forwardInvocation:), (IMP)DistantForward, &distantForward);
  InstallSelector(@"_UIViewServiceViewControllerOperator", NSSelectorFromString(@"_disableAutomaticKeyboardBehavior"), (IMP)AutomaticBehavior, &automaticBehavior);
  InstallSelector(@"UIInputViewController", NSSelectorFromString(@"_autosizeToCurrentKeyboard"), (IMP)NativeAutosize, &nativeAutosize);
  InstallSelector(@"UIInputViewController", NSSelectorFromString(@"_alignsToContentViewController"), (IMP)ContentAlignment, &contentAlignment);
  InstallSelector(@"_UIViewServiceViewControllerOperator", NSSelectorFromString(@"_systemLayoutSizeFittingSize:withHorizontalFittingPriority:verticalFittingPriority:"), (IMP)OperatorFitting, &operatorFitting);
  InstallSelector(@"_UIViewServiceViewControllerOperator", @selector(preferredContentSize), (IMP)OperatorPreferred, &operatorPreferred);
  InstallSelector(@"_UIViewServiceViewControllerOperator", @selector(modalPresentationStyle), (IMP)OperatorPresentation, &operatorPresentation);
}
@end
