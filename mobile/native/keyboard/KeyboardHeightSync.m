// Synchronizes the keyboard's measured height while its remote host is connecting.
// Unknown runtime contracts leave UIKit's normal sizing behavior unchanged.
#import "KeyboardHeightSync.h"

#ifndef CLARIFY_KEYBOARD_HEIGHT_DIAGNOSTICS
#define CLARIFY_KEYBOARD_HEIGHT_DIAGNOSTICS 0
#endif
#if CLARIFY_KEYBOARD_HEIGHT_DIAGNOSTICS
#import <QuartzCore/QuartzCore.h>
#define ClarifyHeightLog(...) NSLog(__VA_ARGS__)
#else
#define ClarifyHeightLog(...) do {} while (0)
#endif
#import <objc/message.h>
#import <objc/runtime.h>
#import <string.h>
#import <math.h>

@interface ClarifyKeyboardHeightState : NSObject
@property(nonatomic, weak) id owner;
@property(nonatomic) BOOL armed;
@property(nonatomic) BOOL publishing;
#if CLARIFY_KEYBOARD_HEIGHT_DIAGNOSTICS
@property(nonatomic) BOOL reportedSkip;
@property(nonatomic) NSUInteger instanceID;
#endif
@end
@implementation ClarifyKeyboardHeightState
#if CLARIFY_KEYBOARD_HEIGHT_DIAGNOSTICS
- (void)dealloc {
    ClarifyHeightLog(@"ClarifyKeyboardHeight event=state-destroyed state=%lu", (unsigned long)self.instanceID);
}
#endif
@end

static char keyboardHeightStateKey;
#if CLARIFY_KEYBOARD_HEIGHT_DIAGNOSTICS
static NSUInteger keyboardHeightStateSequence;
#endif
static void (*keyboardHeightOriginalHostReady)(id, SEL);

static ClarifyKeyboardHeightState *heightStateFor(UIInputViewController *child) {
    ClarifyKeyboardHeightState *state = objc_getAssociatedObject(child, &keyboardHeightStateKey);
    if (!state) {
        state = [ClarifyKeyboardHeightState new];
#if CLARIFY_KEYBOARD_HEIGHT_DIAGNOSTICS
        state.instanceID = ++keyboardHeightStateSequence;
#endif
        objc_setAssociatedObject(child, &keyboardHeightStateKey, state, OBJC_ASSOCIATION_RETAIN_NONATOMIC);
        ClarifyHeightLog(@"ClarifyKeyboardHeight time=%.9f event=state-created state=%lu child=%p", CACurrentMediaTime(), (unsigned long)state.instanceID, child);
    }
    return state;
}

static id heightObjectIvar(id object, const char *name) {
    Ivar ivar = class_getInstanceVariable(object_getClass(object), name);
    const char *encoding = ivar ? ivar_getTypeEncoding(ivar) : NULL;
    return encoding && encoding[0] == '@' ? object_getIvar(object, ivar) : nil;
}

static id heightObjectProperty(id object, NSString *name) {
    SEL selector = NSSelectorFromString(name);
    NSMethodSignature *signature = [object methodSignatureForSelector:selector];
    return signature.numberOfArguments == 2 && signature.methodReturnType[0] == '@' ?
        ((id (*)(id, SEL))objc_msgSend)(object, selector) : nil;
}

static void heightAssociateOwner(id object) {
    if (![NSThread isMainThread]) return;
    id child = heightObjectIvar(object, "_localViewController");
    if (![child isKindOfClass:UIInputViewController.class]) return;
    ClarifyKeyboardHeightState *state = heightStateFor(child);
    if (state.owner != object) {
        // The original host-ready call has returned. A new child is eligible
        // only in a subsequent provisional keyboard layout, never full screen.
#if CLARIFY_KEYBOARD_HEIGHT_DIAGNOSTICS
        state.reportedSkip = NO;
#endif
        state.armed = YES;
    }
    state.owner = object;
    ClarifyHeightLog(@"ClarifyKeyboardHeight time=%.9f event=owner-associated state=%lu child=%p armed=%d policy=ready-layout", CACurrentMediaTime(), (unsigned long)state.instanceID, child, state.armed);
}

static void heightSkipped(ClarifyKeyboardHeightState *state, UIInputViewController *child, NSString *reason) {
#if CLARIFY_KEYBOARD_HEIGHT_DIAGNOSTICS
    if (state.reportedSkip) return;
    state.reportedSkip = YES;
    ClarifyHeightLog(@"ClarifyKeyboardHeight time=%.9f event=skip state=%lu child=%p reason=%@", CACurrentMediaTime(), (unsigned long)state.instanceID, child, reason);
#else
    (void)state; (void)child; (void)reason;
#endif
}

static void heightHostReady(id object, SEL command) {
    keyboardHeightOriginalHostReady(object, command);
    // Do not publish from this callback. Wait for a keyboard-size layout.
    if ([NSThread isMainThread]) heightAssociateOwner(object);
    else {
        __weak id owner = object;
        dispatch_async(dispatch_get_main_queue(), ^{ if (owner) heightAssociateOwner(owner); });
    }
}

void ClarifyKeyboardHeightDidAppear(UIInputViewController *child) {
    if (![NSThread isMainThread]) return;
    ClarifyKeyboardHeightState *state = heightStateFor(child);
    state.armed = NO;
    ClarifyHeightLog(@"ClarifyKeyboardHeight time=%.9f event=appeared state=%lu child=%p", CACurrentMediaTime(), (unsigned long)state.instanceID, child);
}

void ClarifyKeyboardHeightDidDisappear(UIInputViewController *child) {
    if (![NSThread isMainThread]) return;
    ClarifyKeyboardHeightState *state = heightStateFor(child);
    state.owner = nil;
    state.armed = NO;
#if CLARIFY_KEYBOARD_HEIGHT_DIAGNOSTICS
    state.reportedSkip = NO;
#endif
    ClarifyHeightLog(@"ClarifyKeyboardHeight time=%.9f event=closed state=%lu child=%p", CACurrentMediaTime(), (unsigned long)state.instanceID, child);
}

void ClarifyKeyboardHeightDidLayout(UIInputViewController *child) {
    if (![NSThread isMainThread]) {
        ClarifyHeightLog(@"ClarifyKeyboardHeight time=%.9f event=layout-off-main child=%p", CACurrentMediaTime(), child);
        return;
    }
    ClarifyKeyboardHeightState *state = heightStateFor(child);
    UIView *view = child.viewIfLoaded;
    if (!state.armed || state.publishing || !view ||
        view.bounds.size.height <= view.intrinsicContentSize.height + 1) return;
    if (!view.window || !state.owner) { heightSkipped(state, child, @"window-or-owner"); return; }
    // Exclude the temporary full-screen service scene before keyboard placement.
    if (view.bounds.size.height >= view.window.screen.bounds.size.height - 1) return;
    id owner = state.owner;
    if (heightObjectIvar(owner, "_localViewController") != child) { heightSkipped(state, child, @"stale-owner"); return; }
    SEL fitting = NSSelectorFromString(@"_systemLayoutSizeFittingSize:withHorizontalFittingPriority:verticalFittingPriority:");
    id proxy = heightObjectIvar(owner, "_remoteViewControllerProxyToOperator");
    SEL update = NSSelectorFromString(@"__viewServiceInstrinsicContentSizeDidChange:fence:");
    NSMethodSignature *fitSignature = [child methodSignatureForSelector:fitting];
    NSMethodSignature *updateSignature = [proxy methodSignatureForSelector:update];
    if (fitSignature.numberOfArguments != 5 || strncmp(fitSignature.methodReturnType, "{CGSize=", 8) ||
        strncmp([fitSignature getArgumentTypeAtIndex:2], "{CGSize=", 8) ||
        [fitSignature getArgumentTypeAtIndex:3][0] != 'f' || [fitSignature getArgumentTypeAtIndex:4][0] != 'f' ||
        updateSignature.numberOfArguments != 4 || strcmp(updateSignature.methodReturnType, "v") ||
        strncmp([updateSignature getArgumentTypeAtIndex:2], "{CGSize=", 8) ||
        [updateSignature getArgumentTypeAtIndex:3][0] != '@') { heightSkipped(state, child, @"signature"); return; }
    // Fitting can invoke layout; reject recursive publication before calling it.
    state.publishing = YES;
    @try {
        CGSize size = ((CGSize (*)(id, SEL, CGSize, float, float))objc_msgSend)(child, fitting, view.bounds.size, 50, 50);
        if (!isfinite(size.width) || !isfinite(size.height) || size.width <= 0 || size.height <= 0 ||
            view.bounds.size.height <= size.height + 1) { heightSkipped(state, child, @"size"); return; }
        id window = heightObjectProperty(owner, @"_window");
        id scene = heightObjectProperty(window, @"_windowHostingScene");
        id fence = heightObjectProperty(scene, @"_synchronizedDrawingFence");
        SEL invalidate = NSSelectorFromString(@"invalidate");
        NSMethodSignature *invalidateSignature = [fence methodSignatureForSelector:invalidate];
        if (!fence || invalidateSignature.numberOfArguments != 2 || strcmp(invalidateSignature.methodReturnType, "v")) { heightSkipped(state, child, @"fence"); return; }
        @try {
            if (!state.armed || state.owner != owner || heightObjectIvar(owner, "_localViewController") != child) { heightSkipped(state, child, @"owner-changed"); return; }
            if (!view.window || view.bounds.size.height >= view.window.screen.bounds.size.height - 1 ||
                view.bounds.size.height <= size.height + 1) { heightSkipped(state, child, @"layout-changed"); return; }
            state.armed = NO;
            ClarifyHeightLog(@"ClarifyKeyboardHeight time=%.9f event=send state=%lu child=%p root=%.3f size=%@ fence=%@", CACurrentMediaTime(), (unsigned long)state.instanceID, child, view.bounds.size.height, NSStringFromCGSize(size), NSStringFromClass([fence class]));
            ((void (*)(id, SEL, CGSize, id))objc_msgSend)(proxy, update, size, fence);
        } @finally {
            ((void (*)(id, SEL))objc_msgSend)(fence, invalidate);
        }
    } @catch (NSException *exception) {
        (void)exception;
        ClarifyHeightLog(@"ClarifyKeyboardHeight time=%.9f event=exception type=%@", CACurrentMediaTime(), exception.name);
    } @finally {
        state.publishing = NO;
    }
}

@interface ClarifyKeyboardHeightSyncBootstrap : NSObject
@end
@implementation ClarifyKeyboardHeightSyncBootstrap
+ (void)load {
    Class type = NSClassFromString(@"_UIViewServiceViewControllerOperator");
    Method method = class_getInstanceMethod(type, NSSelectorFromString(@"__hostReadyToReceiveMessagesFromServiceViewController"));
    NSMethodSignature *signature = method ? [NSMethodSignature signatureWithObjCTypes:method_getTypeEncoding(method)] : nil;
    ClarifyHeightLog(@"ClarifyKeyboardHeight install signature=%s", method ? method_getTypeEncoding(method) : "missing");
    if (signature.numberOfArguments == 2 && !strcmp(signature.methodReturnType, "v"))
        keyboardHeightOriginalHostReady = (void *)method_setImplementation(method, (IMP)heightHostReady);
}
@end
