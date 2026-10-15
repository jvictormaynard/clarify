// Generated extension fixture only. Never linked into the shipped keyboard.
#import <UIKit/UIKit.h>
#import <QuartzCore/QuartzCore.h>
#import <objc/message.h>
#import <objc/runtime.h>
#import <string.h>
#import <math.h>

@interface ClarifyWarmFenceState : NSObject
@property(nonatomic, weak) id owner;
@property(nonatomic) BOOL appeared;
@property(nonatomic) BOOL armed;
@property(nonatomic) BOOL publishing;
@property(nonatomic) BOOL reportedSkip;
@end
@implementation ClarifyWarmFenceState
@end

static char stateKey;
static void (*originalHostReady)(id, SEL);

static ClarifyWarmFenceState *stateFor(UIInputViewController *child) {
    ClarifyWarmFenceState *state = objc_getAssociatedObject(child, &stateKey);
    if (!state) {
        state = [ClarifyWarmFenceState new];
        objc_setAssociatedObject(child, &stateKey, state, OBJC_ASSOCIATION_RETAIN_NONATOMIC);
    }
    return state;
}

static id objectIvar(id object, const char *name) {
    Ivar ivar = class_getInstanceVariable(object_getClass(object), name);
    const char *encoding = ivar ? ivar_getTypeEncoding(ivar) : NULL;
    return encoding && encoding[0] == '@' ? object_getIvar(object, ivar) : nil;
}

static id objectProperty(id object, NSString *name) {
    SEL selector = NSSelectorFromString(name);
    NSMethodSignature *signature = [object methodSignatureForSelector:selector];
    return signature.numberOfArguments == 2 && signature.methodReturnType[0] == '@' ?
        ((id (*)(id, SEL))objc_msgSend)(object, selector) : nil;
}

static void associateOwner(id object) {
    if (![NSThread isMainThread]) return;
    id child = objectIvar(object, "_localViewController");
    if (![child isKindOfClass:UIInputViewController.class]) return;
    ClarifyWarmFenceState *state = stateFor(child);
    if (state.owner != object) {
        state.appeared = NO; state.armed = NO; state.reportedSkip = NO;
    }
    state.owner = object;
    NSLog(@"ClarifyWarmFence time=%.9f event=owner-associated child=%p", CACurrentMediaTime(), child);
}

static void skipped(ClarifyWarmFenceState *state, UIInputViewController *child, NSString *reason) {
    if (state.reportedSkip) return;
    state.reportedSkip = YES;
    NSLog(@"ClarifyWarmFence time=%.9f event=skip child=%p reason=%@", CACurrentMediaTime(), child, reason);
}

static void hostReady(id object, SEL command) {
    originalHostReady(object, command);
    // No cold publication: let the unmodified extension complete presentation.
    if ([NSThread isMainThread]) associateOwner(object);
    else {
        __weak id owner = object;
        dispatch_async(dispatch_get_main_queue(), ^{ if (owner) associateOwner(owner); });
    }
}

void ClarifyWarmFenceDidAppear(UIInputViewController *child) {
    if (![NSThread isMainThread]) return;
    ClarifyWarmFenceState *state = stateFor(child);
    state.appeared = YES; state.armed = NO;
    NSLog(@"ClarifyWarmFence time=%.9f event=appeared child=%p", CACurrentMediaTime(), child);
}

void ClarifyWarmFenceDidDisappear(UIInputViewController *child) {
    if (![NSThread isMainThread]) return;
    ClarifyWarmFenceState *state = stateFor(child);
    state.armed = state.appeared; state.reportedSkip = NO;
    NSLog(@"ClarifyWarmFence time=%.9f event=armed child=%p value=%d", CACurrentMediaTime(), child, state.armed);
}

void ClarifyWarmFenceLayout(UIInputViewController *child) {
    if (![NSThread isMainThread]) return;
    ClarifyWarmFenceState *state = stateFor(child);
    UIView *view = child.viewIfLoaded;
    if (!state.armed || state.publishing || !view || view.bounds.size.height <= view.intrinsicContentSize.height + 1) return;
    if (!view.window || !state.owner) { skipped(state, child, @"window-or-owner"); return; }
    id owner = state.owner;
    if (objectIvar(owner, "_localViewController") != child) { skipped(state, child, @"stale-owner"); return; }
    SEL fitting = NSSelectorFromString(@"_systemLayoutSizeFittingSize:withHorizontalFittingPriority:verticalFittingPriority:");
    id proxy = objectIvar(owner, "_remoteViewControllerProxyToOperator");
    SEL update = NSSelectorFromString(@"__viewServiceInstrinsicContentSizeDidChange:fence:");
    NSMethodSignature *fitSignature = [child methodSignatureForSelector:fitting];
    NSMethodSignature *updateSignature = [proxy methodSignatureForSelector:update];
    if (fitSignature.numberOfArguments != 5 || strncmp(fitSignature.methodReturnType, "{CGSize=", 8) ||
        strncmp([fitSignature getArgumentTypeAtIndex:2], "{CGSize=", 8) ||
        [fitSignature getArgumentTypeAtIndex:3][0] != 'f' || [fitSignature getArgumentTypeAtIndex:4][0] != 'f' ||
        updateSignature.numberOfArguments != 4 || strcmp(updateSignature.methodReturnType, "v") ||
        strncmp([updateSignature getArgumentTypeAtIndex:2], "{CGSize=", 8) ||
        [updateSignature getArgumentTypeAtIndex:3][0] != '@') { skipped(state, child, @"signature"); return; }
    // Fitting can invoke layout; reject recursive publication before calling it.
    state.publishing = YES;
    @try {
        CGSize size = ((CGSize (*)(id, SEL, CGSize, float, float))objc_msgSend)(child, fitting, view.bounds.size, 50, 50);
        if (!isfinite(size.width) || !isfinite(size.height) || size.width <= 0 || size.height <= 0 ||
            view.bounds.size.height <= size.height + 1) { skipped(state, child, @"size"); return; }
        id window = objectProperty(owner, @"_window");
        id scene = objectProperty(window, @"_windowHostingScene");
        id fence = objectProperty(scene, @"_synchronizedDrawingFence");
        SEL invalidate = NSSelectorFromString(@"invalidate");
        NSMethodSignature *invalidateSignature = [fence methodSignatureForSelector:invalidate];
        if (!fence || invalidateSignature.numberOfArguments != 2 || strcmp(invalidateSignature.methodReturnType, "v")) { skipped(state, child, @"fence"); return; }
        state.armed = NO;
        @try {
            NSLog(@"ClarifyWarmFence time=%.9f event=send child=%p root=%.3f size=%@ fence=%@", CACurrentMediaTime(), child, view.bounds.size.height, NSStringFromCGSize(size), NSStringFromClass([fence class]));
            ((void (*)(id, SEL, CGSize, id))objc_msgSend)(proxy, update, size, fence);
        } @finally {
            ((void (*)(id, SEL))objc_msgSend)(fence, invalidate);
        }
    } @catch (NSException *exception) {
        NSLog(@"ClarifyWarmFence time=%.9f event=exception type=%@", CACurrentMediaTime(), exception.name);
    } @finally {
        state.publishing = NO;
    }
}

@interface KeyboardWarmFenceProbe : NSObject
@end
@implementation KeyboardWarmFenceProbe
+ (void)load {
    Class type = NSClassFromString(@"_UIViewServiceViewControllerOperator");
    Method method = class_getInstanceMethod(type, NSSelectorFromString(@"__hostReadyToReceiveMessagesFromServiceViewController"));
    NSMethodSignature *signature = method ? [NSMethodSignature signatureWithObjCTypes:method_getTypeEncoding(method)] : nil;
    NSLog(@"ClarifyWarmFence install signature=%s", method ? method_getTypeEncoding(method) : "missing");
    if (signature.numberOfArguments == 2 && !strcmp(signature.methodReturnType, "v"))
        originalHostReady = (void *)method_setImplementation(method, (IMP)hostReady);
}
@end
