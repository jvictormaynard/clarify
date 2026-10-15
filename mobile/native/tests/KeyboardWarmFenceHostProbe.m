// Isolated host observer. It does not alter the reported intrinsic size.
#import <UIKit/UIKit.h>
#import <QuartzCore/QuartzCore.h>
#import <objc/runtime.h>
#import <string.h>

static void (*originalIntrinsicApplied)(id, SEL);
static void intrinsicApplied(id object, SEL command) {
    originalIntrinsicApplied(object, command);
    UIView *view = [(UIViewController *)object viewIfLoaded];
    NSLog(@"ClarifyWarmFenceHost time=%.9f event=intrinsic-applied size=%@", CACurrentMediaTime(),
          NSStringFromCGSize(view ? view.intrinsicContentSize : CGSizeZero));
}
@interface KeyboardWarmFenceHostProbe : NSObject
@end
@implementation KeyboardWarmFenceHostProbe
+ (void)load {
    Method method = class_getInstanceMethod(NSClassFromString(@"_UIRemoteInputViewController"),
                                           NSSelectorFromString(@"viewDidInvalidateIntrinsicContentSize"));
    NSMethodSignature *signature = method ? [NSMethodSignature signatureWithObjCTypes:method_getTypeEncoding(method)] : nil;
    if (signature.numberOfArguments == 2 && !strcmp(signature.methodReturnType, "v"))
        originalIntrinsicApplied = (void *)method_setImplementation(method, (IMP)intrinsicApplied);
}
@end
