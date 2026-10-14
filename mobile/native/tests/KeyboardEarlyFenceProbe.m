// Isolated extension fixture only. Test early intrinsic delivery with UIKit's fence.
#import <UIKit/UIKit.h>
#import <QuartzCore/QuartzCore.h>
#import <objc/message.h>
#import <objc/runtime.h>
#import <string.h>
#import <math.h>

static void (*originalHostReady)(id, SEL);

static id objectProperty(id object, NSString *name) {
    SEL selector = NSSelectorFromString(name);
    NSMethodSignature *signature = [object methodSignatureForSelector:selector];
    return signature.numberOfArguments == 2 && signature.methodReturnType[0] == '@' ?
        ((id (*)(id, SEL))objc_msgSend)(object, selector) : nil;
}

static void publishEarlyIntrinsic(id object) {
    Ivar childIvar = class_getInstanceVariable(object_getClass(object), "_localViewController");
    Ivar proxyIvar = class_getInstanceVariable(object_getClass(object), "_remoteViewControllerProxyToOperator");
    UIViewController *child = childIvar ? object_getIvar(object, childIvar) : nil;
    if (![child isKindOfClass:UIInputViewController.class]) {
        child = nil;
        for (UIViewController *candidate in [(UIViewController *)object childViewControllers]) {
            if ([candidate isKindOfClass:UIInputViewController.class]) { child = candidate; break; }
        }
    }
    id proxy = proxyIvar ? object_getIvar(object, proxyIvar) : nil;
    SEL fitting = NSSelectorFromString(@"_systemLayoutSizeFittingSize:withHorizontalFittingPriority:verticalFittingPriority:");
    SEL update = NSSelectorFromString(@"__viewServiceInstrinsicContentSizeDidChange:fence:");
    NSMethodSignature *fitSignature = [child methodSignatureForSelector:fitting];
    NSMethodSignature *updateSignature = [proxy methodSignatureForSelector:update];
    if (fitSignature.numberOfArguments != 5 || strncmp(fitSignature.methodReturnType, "{CGSize=", 8) ||
        strncmp([fitSignature getArgumentTypeAtIndex:2], "{CGSize=", 8) ||
        [fitSignature getArgumentTypeAtIndex:3][0] != 'f' || [fitSignature getArgumentTypeAtIndex:4][0] != 'f' ||
        updateSignature.numberOfArguments != 4 || strcmp(updateSignature.methodReturnType, "v") ||
        strncmp([updateSignature getArgumentTypeAtIndex:2], "{CGSize=", 8) ||
        [updateSignature getArgumentTypeAtIndex:3][0] != '@') {
        NSLog(@"ClarifyOpeningOrder time=%.9f event=early-fence-unavailable reason=signature", CACurrentMediaTime());
        return;
    }
    UIView *view = child.viewIfLoaded;
    if (!view) {
        NSLog(@"ClarifyOpeningOrder time=%.9f event=early-fence-unavailable reason=view", CACurrentMediaTime());
        return;
    }
    CGSize size = ((CGSize (*)(id, SEL, CGSize, float, float))objc_msgSend)(child, fitting, view.bounds.size, 50, 50);
    if (!isfinite(size.width) || !isfinite(size.height) || size.height <= 0) {
        NSLog(@"ClarifyOpeningOrder time=%.9f event=early-fence-unavailable reason=size size=%@", CACurrentMediaTime(), NSStringFromCGSize(size));
        return;
    }
    id window = objectProperty(object, @"_window");
    id scene = objectProperty(window, @"_windowHostingScene");
    id fence = objectProperty(scene, @"_synchronizedDrawingFence");
    SEL invalidate = NSSelectorFromString(@"invalidate");
    if (!fence || ![fence respondsToSelector:invalidate]) {
        NSLog(@"ClarifyOpeningOrder time=%.9f event=early-fence-unavailable reason=fence size=%@", CACurrentMediaTime(), NSStringFromCGSize(size));
        return;
    }
    @try {
        NSLog(@"ClarifyOpeningOrder time=%.9f event=early-fence-send size=%@ fence=%@", CACurrentMediaTime(), NSStringFromCGSize(size), NSStringFromClass([fence class]));
        ((void (*)(id, SEL, CGSize, id))objc_msgSend)(proxy, update, size, fence);
    } @finally {
        ((void (*)(id, SEL))objc_msgSend)(fence, invalidate);
    }
}

static void hostReady(id object, SEL command) {
    originalHostReady(object, command);
    publishEarlyIntrinsic(object);
}

@interface KeyboardEarlyFenceProbe : NSObject
@end
@implementation KeyboardEarlyFenceProbe
+ (void)load {
    Class type = NSClassFromString(@"_UIViewServiceViewControllerOperator");
    Method method = class_getInstanceMethod(type, NSSelectorFromString(@"__hostReadyToReceiveMessagesFromServiceViewController"));
    NSLog(@"ClarifyOpeningOrder early-fence-install signature=%s", method ? method_getTypeEncoding(method) : "missing");
    NSMethodSignature *signature = method ? [NSMethodSignature signatureWithObjCTypes:method_getTypeEncoding(method)] : nil;
    if (signature.numberOfArguments == 2 && !strcmp(signature.methodReturnType, "v")) {
        originalHostReady = (void *)method_setImplementation(method, (IMP)hostReady);
    }
}
@end
