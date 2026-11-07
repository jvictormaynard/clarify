//
//  KBHostArbiterHook.m
//  KeyboardHostBundleID
//

#import "KBHostArbiterHook.h"
#import <UIKit/UIKit.h>
#import <objc/runtime.h>
#import <objc/message.h>
#import <os/lock.h>
#import <string.h>
#import <dlfcn.h>
#import <stdlib.h>

// All private UIKit symbols are resolved at runtime so they never appear as
// static references. Names are kept as string constants.
static NSString *const kArbiterClientClassName   = @"_UIKeyboardArbiterClient";
static NSString *const kDestinationClassName     = @"_UIKeyboardArbiterClientInputDestination";
static NSString *const kEnabledSelectorName      = @"enabled";
static NSString *const kAutoSharedSelectorName   = @"automaticSharedArbiterClient";
static NSString *const kCheckConnSelectorName    = @"checkConnection";
static NSString *const kSwizzleSelectorName      = @"queue_keyboardChanged:onComplete:";
static NSString *const kHandledSelectorName      = @"_didHandleKeyboardClientChange:shouldConsiderSnapshottingKeyboard:isLocalEvent:";
static NSString *const kSourceBundleIdKey        = @"_sourceBundleIdentifier";

static os_unfair_lock sHookLock = OS_UNFAIR_LOCK_INIT;
static NSString *_Nullable sLastCapturedBundleId = nil;
static uint64_t sCaptureGeneration = 0;
static uint64_t sInvalidationGeneration = 0;
static IMP _Nullable sOriginalIMP = NULL;
static IMP _Nullable sOriginalHandledIMP = NULL;
static BOOL sEnabledInstalled = NO;

#pragma mark - Validation

// Unlike Swift KVC, Objective-C can catch an unknown-key exception when a
// private OS field changes. Never invoke an unchecked method through perform:.
static id ObjectResult(id receiver, NSString *name) {
    SEL selector = NSSelectorFromString(name);
    if (![receiver respondsToSelector:selector]) return nil;
    NSMethodSignature *signature = [receiver methodSignatureForSelector:selector];
    if (!signature || signature.numberOfArguments != 2 || signature.methodReturnType[0] != '@') return nil;
    return ((id (*)(id, SEL))objc_msgSend)(receiver, selector);
}

static BOOL IsAcceptableBundleId(NSString *_Nullable bid) {
    if (bid.length == 0) return NO;
    if (![bid containsString:@"."]) return NO;
    if ([bid isEqualToString:@"<null>"] || [bid isEqualToString:@"(null)"]) return NO;
    if ([bid isEqualToString:[NSBundle mainBundle].bundleIdentifier]) return NO;
    // Real system hosts also use com.apple.*. A namespace alone cannot
    // distinguish a host app from an internal UIKit identity.
    return YES;
}

static void CommitHostBundleId(NSString *_Nullable bid) {
    NSString *accepted = IsAcceptableBundleId(bid) ? [bid copy] : nil;

    os_unfair_lock_lock(&sHookLock);
    // An unknown/invalid destination invalidates the previous host too.
    sLastCapturedBundleId = accepted;
    sCaptureGeneration += 1;
    uint64_t generation = sCaptureGeneration;
    uint64_t invalidation = sInvalidationGeneration;
    os_unfair_lock_unlock(&sHookLock);
    NSLog(@"ClarifyActivationTrace capture generation=%llu invalidation=%llu source=%@", (unsigned long long)generation, (unsigned long long)invalidation, accepted ?: @"unknown");
}

#pragma mark - Trampolines

// Replacement for -[_UIKeyboardArbiterClientInputDestination queue_keyboardChanged:onComplete:].
// The bundle identifier lives on the `change` argument (arg1), not on `self`.
static void CaptureHost(id change) {
    NSString *bundleId = nil;
    if (change) {
        @try {
            id value = [change valueForKey:kSourceBundleIdKey];
            if ([value isKindOfClass:[NSString class]]) {
                bundleId = (NSString *)value;
            }
        } @catch (__unused NSException *e) {
            // Swallow KVC failures so the original IMP still runs.
        }
    }
    CommitHostBundleId(bundleId);
}

static void SwizzledKeyboardChanged(id self, SEL _cmd, id change, id completion) {
    CaptureHost(change);
    if (sOriginalIMP) {
        ((void (*)(id, SEL, id, id))sOriginalIMP)(self, _cmd, change, completion);
    }
}

// Current UIKit can deliver its initial connection update directly to this
// handler, without passing through queue_keyboardChanged:onComplete:.
static BOOL SwizzledHandledChange(id self, SEL _cmd, id change, BOOL snapshot, BOOL local) {
    CaptureHost(change);
    if (sOriginalHandledIMP) {
        return ((BOOL (*)(id, SEL, id, BOOL, BOOL))sOriginalHandledIMP)(self, _cmd, change, snapshot, local);
    }
    return NO;
}

static BOOL IsBooleanType(const char *type) { return strcmp(type, "B") == 0 || strcmp(type, "c") == 0; }

static BOOL ValidChangeMethod(Method method, BOOL flags) {
    if (!method || method_getNumberOfArguments(method) != (flags ? 5 : 4)) return NO;
    char result[16] = {0}, first[16] = {0}, second[16] = {0}, third[16] = {0};
    method_getReturnType(method, result, sizeof(result));
    method_getArgumentType(method, 2, first, sizeof(first));
    method_getArgumentType(method, 3, second, sizeof(second));
    if ((flags ? !IsBooleanType(result) : strcmp(result, "v") != 0) || first[0] != '@') return NO;
    if (!flags) return second[0] == '@';
    method_getArgumentType(method, 4, third, sizeof(third));
    return IsBooleanType(second) && IsBooleanType(third);
}

// Replacement for +[_UIKeyboardArbiterClient enabled]. iOS 26.4 gates the
// destination-changed dispatch on this class method; if it returns NO the
// trampoline above never fires. Force it to YES inside the keyboard process.
static BOOL AlwaysEnabledIMP(__unused id self, __unused SEL _cmd) {
    return YES;
}

#pragma mark - Install

static void TraceHostClass(Class cls) {
    for (NSUInteger depth = 0; cls && cls != NSObject.class && depth < 4; depth++, cls = class_getSuperclass(cls)) {
        unsigned int count = 0;
        Method *methods = class_copyMethodList(cls, &count);
        for (unsigned int i = 0; i < count; i++) {
            NSString *name = NSStringFromSelector(method_getName(methods[i]));
            NSString *lower = name.lowercaseString;
            if ([lower containsString:@"host"] || [lower containsString:@"connection"] || [lower containsString:@"destination"] || [lower containsString:@"request"] || [lower containsString:@"client"] || [lower containsString:@"source"] || [lower containsString:@"bundle"] || [lower containsString:@"pid"] || [lower containsString:@"identifier"] || [lower containsString:@"state"] || [lower containsString:@"remote"] || [lower containsString:@"interface"]) {
                NSLog(@"ClarifyHostRuntime method %@ %@ %s", NSStringFromClass(cls), name, method_getTypeEncoding(methods[i]));
            }
        }
        free(methods);
        Ivar *ivars = class_copyIvarList(cls, &count);
        for (unsigned int i = 0; i < count; i++) {
            NSLog(@"ClarifyHostRuntime ivar %@ %s %s", NSStringFromClass(cls), ivar_getName(ivars[i]), ivar_getTypeEncoding(ivars[i]));
        }
        free(ivars);
    }
}

static void TraceHostProtocol(Protocol *protocol) {
    if (!protocol) return;
    for (NSUInteger required = 0; required < 2; required++) {
        unsigned int count = 0;
        struct objc_method_description *methods = protocol_copyMethodDescriptionList(protocol, required != 0, YES, &count);
        for (unsigned int i = 0; i < count; i++) {
            NSLog(@"ClarifyHostRuntime protocol %s %@ %s", protocol_getName(protocol), NSStringFromSelector(methods[i].name), methods[i].types ?: "missing");
        }
        free(methods);
    }
}

static void TraceHostConnection(id connection) {
    NSLog(@"ClarifyHostRuntime connection class=%@", NSStringFromClass([connection class]));
    TraceHostClass([connection class]);
    if ([connection isKindOfClass:NSXPCConnection.class]) {
        TraceHostProtocol([(NSXPCConnection *)connection remoteObjectInterface].protocol);
    }
}

static void TraceHostState(id state) {
    NSLog(@"ClarifyHostRuntime current state=%@", state);
    TraceHostClass([state class]);
    for (NSString *key in @[@"processIdentifier", @"hostProcessIdentifier", @"sourceBundleIdentifier", @"hostBundleIdentifier"]) {
        @try {
            id value = [state valueForKey:key];
            NSLog(@"ClarifyHostIdentity %@ type=%@ value=%@", key, NSStringFromClass([value class]), [value isKindOfClass:NSNumber.class] || [value isKindOfClass:NSString.class] ? value : @"unknown");
        } @catch (__unused NSException *error) { NSLog(@"ClarifyHostIdentity %@ unavailable", key); }
    }
}

@implementation KBHostArbiterHook

+ (nullable NSString *)legacyHostBundleIDForController:(UIInputViewController *)controller {
    if (!NSThread.isMainThread || !controller.isViewLoaded || !controller.view.window) return nil;
    NSLog(@"ClarifyHostRuntime controller=%@ parent=%@", NSStringFromClass(controller.class), NSStringFromClass(controller.parentViewController.class));
    TraceHostClass(controller.class);
    TraceHostClass(controller.parentViewController.class);
    for (id target in @[controller, controller.parentViewController ?: NSNull.null]) {
        for (NSString *key in @[@"_hostPID", @"_hostProcessIdentifier", @"_hostBundleIdentifier"]) {
            @try {
                id value = [target valueForKey:key];
                NSLog(@"ClarifyHostRuntime probe %@ %@ type=%@ number=%@", NSStringFromClass([target class]), key, NSStringFromClass([value class]), [value isKindOfClass:NSNumber.class] ? value : @"not-number");
            } @catch (__unused NSException *error) { NSLog(@"ClarifyHostRuntime probe %@ %@ unavailable", NSStringFromClass([target class]), key); }
        }
    }
    @try {
        id pid = [controller.parentViewController valueForKey:@"_hostPID"];
        NSLog(@"ClarifyHostRuntime parent pid=%@", pid);
        TraceHostState(ObjectResult(ObjectResult(NSClassFromString(kArbiterClientClassName), kAutoSharedSelectorName), @"currentClientState"));
        if (![pid isKindOfClass:NSNumber.class] || [pid intValue] <= 0) return nil;
        id service = ObjectResult(NSClassFromString(@"PKService"), @"defaultService");
        id personalities = ObjectResult(service, @"personalities");
        NSLog(@"ClarifyHostRuntime service=%@ personalities=%@", NSStringFromClass([service class]), NSStringFromClass([personalities class]));
        if (![personalities isKindOfClass:NSDictionary.class]) return nil;
        NSString *ownID = NSBundle.mainBundle.bundleIdentifier;
        if (!ownID) return nil;
        id hosts = [personalities objectForKey:ownID];
        NSLog(@"ClarifyHostRuntime personality keys=%@ own=%@ hosts=%@", [personalities allKeys], ownID, NSStringFromClass([hosts class]));
        if (![hosts isKindOfClass:NSDictionary.class]) return nil;
        id host = [hosts objectForKey:pid];
        NSLog(@"ClarifyHostRuntime host record=%@", NSStringFromClass([host class]));
        TraceHostClass([host class]);
        id connection = ObjectResult(host, @"connection");
        id xpc = ObjectResult(connection, @"_xpcConnection");
        NSLog(@"ClarifyHostRuntime host keys=%@ connection=%@ xpc=%@", [hosts allKeys], NSStringFromClass([connection class]), NSStringFromClass([xpc class]));
        if (!xpc) return nil;
        void *handle = dlopen("/usr/lib/system/libxpc.dylib", RTLD_NOW);
        if (!handle) return nil;
        char *(*copyBundleID)(id) = (char *(*)(id))dlsym(handle, "xpc_connection_copy_bundle_id");
        char *value = copyBundleID ? copyBundleID(xpc) : NULL;
        NSString *bundleID = value ? [NSString stringWithUTF8String:value] : nil;
        free(value); dlclose(handle);
        return IsAcceptableBundleId(bundleID) ? bundleID : nil;
    } @catch (NSException *error) { NSLog(@"ClarifyHostRuntime legacy exception=%@", error.name); return nil; }
}

+ (void)load {
    if (@available(iOS 26.4, *)) {
        [self installHooks];
    }
}

+ (void)installHooks {
    os_unfair_lock_lock(&sHookLock);

    // Step 1: force +[_UIKeyboardArbiterClient enabled] to return YES so the
    // arbiter dispatches destination-changed callbacks into our swizzle.
    Class clientCls = NSClassFromString(kArbiterClientClassName);
    if (clientCls && !sEnabledInstalled) {
        SEL enabledSel = NSSelectorFromString(kEnabledSelectorName);
        Method enabledMethod = class_getClassMethod(clientCls, enabledSel);
        char returnType[16] = {0};
        if (enabledMethod) method_getReturnType(enabledMethod, returnType, sizeof(returnType));
        if (enabledMethod && method_getNumberOfArguments(enabledMethod) == 2
            && (strcmp(returnType, "B") == 0 || strcmp(returnType, "c") == 0)) {
            method_setImplementation(enabledMethod, (IMP)&AlwaysEnabledIMP);
            sEnabledInstalled = YES;
        }
    }

    // Step 2: swap the destination's queue_keyboardChanged:onComplete: IMP.
    Class destCls = NSClassFromString(kDestinationClassName);
    SEL sel = NSSelectorFromString(kSwizzleSelectorName);
    Method method = destCls ? class_getInstanceMethod(destCls, sel) : NULL;
    if (!sOriginalIMP && ValidChangeMethod(method, NO)) {
        sOriginalIMP = method_getImplementation(method);
        method_setImplementation(method, (IMP)&SwizzledKeyboardChanged);
    }
    Method handled = destCls ? class_getInstanceMethod(destCls, NSSelectorFromString(kHandledSelectorName)) : NULL;
    if (!sOriginalHandledIMP && ValidChangeMethod(handled, YES)) {
        sOriginalHandledIMP = method_getImplementation(handled);
        method_setImplementation(handled, (IMP)&SwizzledHandledChange);
    }
    os_unfair_lock_unlock(&sHookLock);
}

+ (void)activeArbiterCheck {
    if (@available(iOS 26.4, *)) {
        // fall through
    } else {
        return;
    }

    [self installHooks];
    Class cls = NSClassFromString(kArbiterClientClassName);
    if (!cls) return;

    SEL getter = NSSelectorFromString(kAutoSharedSelectorName);
    if (![cls respondsToSelector:getter]) return;
    NSMethodSignature *getterSignature = [cls methodSignatureForSelector:getter];
    if (!getterSignature || getterSignature.numberOfArguments != 2
        || getterSignature.methodReturnType[0] != '@') return;

    @try {
      id (*getMsg)(id, SEL) = (id (*)(id, SEL))objc_msgSend;
      id client = getMsg(cls, getter);
      if (!client) return; // lazy initialization not complete yet; try again later
      static dispatch_once_t traced;
      dispatch_once(&traced, ^{ TraceHostClass([client class]); TraceHostClass(NSClassFromString(kDestinationClassName)); });
      // UIKit may load the destination class after this image's +load.
      [self installHooks];
      SEL ping = NSSelectorFromString(kCheckConnSelectorName);
      if (![client respondsToSelector:ping]) return;
      NSMethodSignature *pingSignature = [client methodSignatureForSelector:ping];
      if (!pingSignature || pingSignature.numberOfArguments != 2
          || strcmp(pingSignature.methodReturnType, "v") != 0) return;
      void (*pingMsg)(id, SEL) = (void (*)(id, SEL))objc_msgSend;
      NSLog(@"ClarifyActivationTrace ping begin");
      pingMsg(client, ping);
      NSLog(@"ClarifyActivationTrace ping end");
      id state = ObjectResult(client, @"currentClientState");
      TraceHostState(state);
      TraceHostConnection(ObjectResult(client, @"connection"));
      TraceHostConnection(ObjectResult(client, @"arbiterConnection"));
    } @catch (__unused NSException *error) { /* Unknown runtime: use manual return. */ }
}

+ (nullable NSString *)lastCapturedHostBundleId {
    os_unfair_lock_lock(&sHookLock);
    NSString *bid = [sLastCapturedBundleId copy];
    os_unfair_lock_unlock(&sHookLock);
    return IsAcceptableBundleId(bid) ? bid : nil;
}

+ (uint64_t)captureGeneration {
    os_unfair_lock_lock(&sHookLock);
    uint64_t generation = sCaptureGeneration;
    os_unfair_lock_unlock(&sHookLock);
    return generation;
}

+ (nullable NSString *)hostBundleIdCapturedAfterGeneration:(uint64_t)generation {
    os_unfair_lock_lock(&sHookLock);
    BOOL fresh = sCaptureGeneration != generation && sInvalidationGeneration <= generation;
    uint64_t current = sCaptureGeneration;
    uint64_t invalidation = sInvalidationGeneration;
    NSString *bid = fresh ? [sLastCapturedBundleId copy] : nil;
    os_unfair_lock_unlock(&sHookLock);
    NSLog(@"ClarifyActivationTrace query baseline=%llu current=%llu invalidation=%llu fresh=%d source=%@", (unsigned long long)generation, (unsigned long long)current, (unsigned long long)invalidation, fresh, bid ?: @"unknown");
    return bid;
}

+ (void)invalidateCache {
    os_unfair_lock_lock(&sHookLock);
    sLastCapturedBundleId = nil;
    sCaptureGeneration += 1;
    sInvalidationGeneration = sCaptureGeneration;
    uint64_t generation = sCaptureGeneration;
    os_unfair_lock_unlock(&sHookLock);
    NSLog(@"ClarifyActivationTrace invalidate generation=%llu", (unsigned long long)generation);
}

@end
