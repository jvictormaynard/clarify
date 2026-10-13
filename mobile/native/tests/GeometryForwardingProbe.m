// Diagnostic only. Do not compile these interventions into the product.
#import <UIKit/UIKit.h>
#import <objc/runtime.h>
#import <objc/message.h>
#import <string.h>
#import "GeometryConfig.h"

static IMP windowInit;
static IMP handleFactory;
static IMP targetedForward;
static __weak UIViewController *geometryParent;
NSString *ClarifyGeometryVariant(void) {
  return [NSString stringWithContentsOfFile:CLARIFY_GEOMETRY_CONFIG encoding:NSUTF8StringEncoding error:nil] ?: @"baseline";
}
static void PublishSize(UIViewController *parent) {
  Ivar ivar = parent ? class_getInstanceVariable(object_getClass(parent), "_remoteViewControllerProxyToOperator") : NULL;
  id proxy = ivar ? object_getIvar(parent, ivar) : nil;
  SEL selector = NSSelectorFromString(@"__viewServiceInstrinsicContentSizeDidChange:fence:");
  NSMethodSignature *signature = [proxy methodSignatureForSelector:selector];
  if (signature.numberOfArguments != 4 || strcmp(signature.methodReturnType, "v") ||
      strncmp([signature getArgumentTypeAtIndex:2], "{CGSize=", 8) || [signature getArgumentTypeAtIndex:3][0] != '@') return;
  CGSize size = CGSizeMake(UIScreen.mainScreen.bounds.size.width, 216);
  ((void (*)(id, SEL, CGSize, id))objc_msgSend)(proxy, selector, size, nil);
  NSLog(@"ClarifyInitialSize published %@ %@", ClarifyGeometryVariant(), NSStringFromCGSize(size));
}
void ClarifyGeometryPrepareParent(UIViewController *parent) {
  geometryParent = parent;
  if ([ClarifyGeometryVariant() isEqualToString:@"early-parent"]) PublishSize(parent);
}
void ClarifyGeometryConfigure(UIInputViewController *controller) {
  geometryParent = controller.parentViewController;
  if ([ClarifyGeometryVariant() isEqualToString:@"early-parent"]) PublishSize(geometryParent);
}
void ClarifyGeometryLogController(UIInputViewController *controller, NSString *phase) {}

static id WindowInit(id self, SEL command, CGRect frame) {
  if ([ClarifyGeometryVariant() isEqualToString:@"initial-window"]) {
    NSLog(@"ClarifyInitialSize window %@ -> 216", NSStringFromCGRect(frame));
    frame.size.height = 216;
  }
  return ((id (*)(id, SEL, CGRect))windowInit)(self, command, frame);
}
static id HandleFactory(id self, SEL command, unsigned int contextID, CGAffineTransform transform, CGRect frame) {
  if ([ClarifyGeometryVariant() isEqualToString:@"initial-handle"]) {
    NSLog(@"ClarifyInitialSize handle %@ -> 216", NSStringFromCGRect(frame));
    frame.size.height = 216;
  }
  return ((id (*)(id, SEL, unsigned int, CGAffineTransform, CGRect))handleFactory)(self, command, contextID, transform, frame);
}
static void TargetedForward(id self, SEL command, NSInvocation *invocation) {
  if ([ClarifyGeometryVariant() isEqualToString:@"preempt-size"] &&
      [NSStringFromSelector(invocation.selector) hasPrefix:@"__setContentSize:"] &&
      invocation.methodSignature.numberOfArguments > 2 &&
      !strncmp([invocation.methodSignature getArgumentTypeAtIndex:2], "{CGSize=", 8)) {
    CGSize size; [invocation getArgument:&size atIndex:2];
    if (size.height > 216) PublishSize(geometryParent);
  }
  ((void (*)(id, SEL, NSInvocation *))targetedForward)(self, command, invocation);
}
static void Install(Class cls, SEL selector, IMP replacement, IMP *original) {
  Method method = cls ? class_getInstanceMethod(cls, selector) : NULL;
  if (!method) { NSLog(@"ClarifyInitialSize missing %@", NSStringFromSelector(selector)); return; }
  *original = method_getImplementation(method);
  if (!class_addMethod(cls, selector, replacement, method_getTypeEncoding(method))) method_setImplementation(method, replacement);
}
@interface ClarifyInitialGeometryProbe : NSObject @end
@implementation ClarifyInitialGeometryProbe
+ (void)load {
  Install(NSClassFromString(@"_UIHostedWindow"), @selector(initWithFrame:), (IMP)WindowInit, &windowInit);
  Install(object_getClass(NSClassFromString(@"_UIHostedWindowHostingHandle")),
          NSSelectorFromString(@"hostedWindowHostingHandleWithContextID:rootLayerTransform:rootLayerFrame:"), (IMP)HandleFactory, &handleFactory);
  Install(NSClassFromString(@"_UITargetedProxy"), @selector(forwardInvocation:), (IMP)TargetedForward, &targetedForward);
}
@end
