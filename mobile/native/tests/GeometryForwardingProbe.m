// Isolated diagnostic only. Do not compile into the product.
#import <UIKit/UIKit.h>
#import <objc/runtime.h>
#import "GeometryConfig.h"

static IMP originalChildBehavior, originalParentBehavior, originalResponder;
NSString *ClarifyGeometryVariant(void) {
  return [NSString stringWithContentsOfFile:CLARIFY_GEOMETRY_CONFIG encoding:NSUTF8StringEncoding error:nil] ?: @"baseline";
}
void ClarifyGeometryPrepareParent(UIViewController *parent) {}
void ClarifyGeometryConfigure(UIInputViewController *controller) {}
void ClarifyGeometryFinish(void) {}
void ClarifyGeometryLogController(UIInputViewController *controller, NSString *phase) {}
static BOOL ChildBehavior(id self, SEL selector) {
  NSString *variant = ClarifyGeometryVariant();
  if ([variant isEqualToString:@"child-no-auto"] || [variant isEqualToString:@"both-no-auto"]) return YES;
  return ((BOOL (*)(id,SEL))originalChildBehavior)(self,selector);
}
static BOOL ParentBehavior(id self, SEL selector) {
  if ([ClarifyGeometryVariant() isEqualToString:@"both-no-auto"]) return YES;
  return ((BOOL (*)(id,SEL))originalParentBehavior)(self,selector);
}
static BOOL CanBecome(id self, SEL selector) {
  if ([ClarifyGeometryVariant() isEqualToString:@"no-first-responder"]) return NO;
  return ((BOOL (*)(id,SEL))originalResponder)(self,selector);
}
static void Install(Class cls, NSString *name, IMP replacement, IMP *original) {
  SEL selector = NSSelectorFromString(name); Method method = cls ? class_getInstanceMethod(cls,selector) : NULL;
  if (!method) { NSLog(@"ClarifyResponderProbe missing %@", name); return; }
  *original = method_getImplementation(method);
  if (!class_addMethod(cls,selector,replacement,method_getTypeEncoding(method))) method_setImplementation(method,replacement);
}
@interface ClarifyResponderProbe : NSObject @end
@implementation ClarifyResponderProbe
+ (void)load {
  Install(UIInputViewController.class, @"_disablesAutomaticKeyboardBehavior", (IMP)ChildBehavior, &originalChildBehavior);
  Install(NSClassFromString(@"_UIViewServiceViewControllerOperator"), @"_disablesAutomaticKeyboardBehavior", (IMP)ParentBehavior, &originalParentBehavior);
  Install(UIInputViewController.class, @"_canBecomeFirstResponder", (IMP)CanBecome, &originalResponder);
}
@end
