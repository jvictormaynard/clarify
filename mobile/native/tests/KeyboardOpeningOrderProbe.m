// Isolated simulator fixture only. Preserve original arguments and callbacks.
#import <UIKit/UIKit.h>
#import <QuartzCore/QuartzCore.h>
#import <objc/runtime.h>

static void (*originalAppearance)(id, SEL, BOOL, NSInteger, UITraitCollection *, CGFloat, BOOL, void (^)(CGSize));
static void (*originalIntrinsicApplied)(id, SEL);

static void appearance(id object, SEL command, BOOL animated, NSInteger orientation,
                       UITraitCollection *traits, CGFloat statusHeight, BOOL underlaps,
                       void (^reply)(CGSize)) {
    NSLog(@"ClarifyOpeningOrder time=%.9f event=appearance-request", CACurrentMediaTime());
    if (!reply) {
        originalAppearance(object, command, animated, orientation, traits, statusHeight, underlaps, reply);
        return;
    }
    originalAppearance(object, command, animated, orientation, traits, statusHeight, underlaps, ^(CGSize size) {
        NSLog(@"ClarifyOpeningOrder time=%.9f event=appearance-ack size=%@", CACurrentMediaTime(), NSStringFromCGSize(size));
        reply(size);
    });
}

static void intrinsicApplied(id object, SEL command) {
    UIView *view = [(UIViewController *)object viewIfLoaded];
    NSLog(@"ClarifyOpeningOrder time=%.9f event=intrinsic-applied size=%@", CACurrentMediaTime(), NSStringFromCGSize(view ? view.intrinsicContentSize : CGSizeZero));
    originalIntrinsicApplied(object, command);
}

static IMP observe(NSString *className, NSString *name, IMP replacement) {
    Class type = NSClassFromString(className);
    Method method = class_getInstanceMethod(type, NSSelectorFromString(name));
    NSLog(@"ClarifyOpeningOrder install %@ %@ signature=%s", className, name, method ? method_getTypeEncoding(method) : "missing");
    return method ? method_setImplementation(method, replacement) : NULL;
}

@interface KeyboardOpeningOrderProbe : NSObject
@end
@implementation KeyboardOpeningOrderProbe
+ (void)load {
    originalAppearance = (void *)observe(@"_UIViewServiceViewControllerOperator",
        @"__hostViewWillAppear:inInterfaceOrientation:traitCollection:statusBarHeight:underlapsStatusBar:completionHandler:", (IMP)appearance);
    originalIntrinsicApplied = (void *)observe(@"_UIRemoteInputViewController", @"viewDidInvalidateIntrinsicContentSize", (IMP)intrinsicApplied);
}
@end
