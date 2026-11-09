#import "ClarifyPrivateWritingToolsBridge.h"
#import <objc/runtime.h>
#import <dlfcn.h>
#import <TargetConditionals.h>
#import <stdbool.h>
#import <stdlib.h>
#import <string.h>

// Declarations only; every private send is guarded against the loaded method.
// https://github.com/qingralf/iOS26-Runtime-Headers/blob/cbf1d4c4122f3c6807eba36693581882640e5c6c/PrivateFrameworks/WritingToolsUI.framework/WTWritingToolsController.h
@interface NSObject (ClarifyPrivateWritingToolsDeclarations)
+ (bool)isAvailable;
- (instancetype)initWithTool:(long long)tool prompt:(id)prompt;
- (void)setSourceResponder:(id)responder sourceTextInput:(id)input;
- (void)startWritingTools;
- (void)endWritingTools;
- (bool)isWritingToolsActive;
- (void)_startRewritingFromCandidateBar;
- (void)_startWritingToolsWithTool:(id)tool prompt:(id)prompt sender:(id)sender;
- (void)_endWritingTools;
- (bool)_isWritingToolsActive;
- (bool)_supportsWritingTools;
@end

static const void *CWSessionKey = &CWSessionKey;
static void *CWTextComposerHandle;
static void *CWWritingToolsHandle;

@interface ClarifyPrivateWritingToolsSession : NSObject
@property (nonatomic, weak) UITextView *textView;
@property (nonatomic) BOOL observedActive;
@property (nonatomic) BOOL endRequested;
@property (nonatomic) NSUInteger observationGeneration;
@property (nonatomic) NSTimeInterval deadline;
@end
@implementation ClarifyPrivateWritingToolsSession
@end

// One UI session, including uncertain startup. No direct service work is admitted.
static ClarifyPrivateWritingToolsSession *CWSession;
static NSString *CWLastEndState = @"none";

// Let UIKit own its controller, delegate, keyboard suppression and teardown.
// Direct WTWritingToolsController allocation bypasses this responder setup.
// iOS 26 selector declarations:
// https://github.com/qingralf/iOS26-Runtime-Headers/blob/cbf1d4c4122f3c6807eba36693581882640e5c6c/PrivateFrameworks/UIKitCore.framework/UIResponder.h
// Responder setup and string tool identifiers from recovered UIKit methods:
// https://github.com/EthanArbuckle/iPhone18-3_26.1_23B85_Restore/blob/90aa0cfe59d9682b4265e1354c8b19ec3c7823ab/System/Library/PrivateFrameworks/UIKitCore.framework/UIKitCore/UIResponder.mm
// https://github.com/EthanArbuckle/iPhone17-1_18.2_22C152_Restore/blob/e26ed4563f78871c59d2d96856756a65d62517e5/System/Library/PrivateFrameworks/WritingToolsUI.framework/WTWritingToolsController.m

static BOOL CWPlatform(void) {
#if TARGET_OS_IOS && !TARGET_OS_SIMULATOR && !TARGET_OS_MACCATALYST
  if (@available(iOS 18.0, *)) return YES;
#endif
  return NO;
}

static void CWLoad(void) {
  static dispatch_once_t once;
  dispatch_once(&once, ^{
    if (!CWPlatform()) return;
    CWTextComposerHandle = dlopen("/System/Library/PrivateFrameworks/TextComposer.framework/TextComposer", RTLD_LAZY | RTLD_LOCAL);
    CWWritingToolsHandle = dlopen("/System/Library/PrivateFrameworks/WritingToolsUI.framework/WritingToolsUI", RTLD_LAZY | RTLD_LOCAL);
    // Keep handles open: runtime classes can outlive this bridge.
  });
}

static BOOL CWType(char *actual, const char *expected) {
  BOOL matches = actual && strcmp(actual, expected) == 0;
  free(actual);
  return matches;
}

// Use runtime metadata, not forwarding or an untrusted methodSignature override.
static BOOL CWMethod(Class cls, BOOL classMethod, SEL selector,
                     const char *result, const char * const *arguments, unsigned count) {
  if (!cls) return NO;
  Method method = classMethod ? class_getClassMethod(cls, selector) : class_getInstanceMethod(cls, selector);
  if (!method || method_getNumberOfArguments(method) != count + 2) return NO;
  if (!CWType(method_copyReturnType(method), result)
      || !CWType(method_copyArgumentType(method, 0), @encode(id))
      || !CWType(method_copyArgumentType(method, 1), @encode(SEL))) return NO;
  for (unsigned index = 0; index < count; index++) {
    if (!CWType(method_copyArgumentType(method, index + 2), arguments[index])) return NO;
  }
  return YES;
}

static BOOL CWUIShape(Class cls) {
  const char *initArgs[] = { @encode(long long), @encode(id) };
  const char *sourceArgs[] = { @encode(id), @encode(id) };
  return CWMethod(cls, YES, @selector(alloc), @encode(id), NULL, 0)
    && CWMethod(cls, YES, @selector(isAvailable), @encode(bool), NULL, 0)
    && CWMethod(cls, NO, @selector(initWithTool:prompt:), @encode(id), initArgs, 2)
    && CWMethod(cls, NO, @selector(setSourceResponder:sourceTextInput:), @encode(void), sourceArgs, 2)
    && CWMethod(cls, NO, @selector(startWritingTools), @encode(void), NULL, 0)
    && CWMethod(cls, NO, @selector(isWritingToolsActive), @encode(bool), NULL, 0);
}

static NSString *CWEncoding(Class cls, BOOL classMethod, SEL selector) {
  Method method = classMethod ? class_getClassMethod(cls, selector) : class_getInstanceMethod(cls, selector);
  const char *types = method ? method_getTypeEncoding(method) : NULL;
  return types ? ([[NSString alloc] initWithBytes:types length:strnlen(types, 1024) encoding:NSUTF8StringEncoding] ?: @"unreadable") : @"unavailable";
}

static BOOL CWStyle(NSString *style, long long *tool) {
  // These are WTRequestedTool values, NOT TextComposer rewritingType strings.
  // https://github.com/WebKit/WebKit/blob/main/Source/WebCore/PAL/pal/spi/cocoa/WritingToolsSPI.h
  if ([style isEqualToString:@"default"]) *tool = 2;
  else if ([style isEqualToString:@"formal"]) *tool = 12;
  else if ([style isEqualToString:@"casual"]) *tool = 11;
  else return NO;
  return YES;
}

static BOOL CWResponderShape(Class cls) {
  const char *args[] = { @encode(id), @encode(id), @encode(id) };
  return CWMethod(cls, NO, @selector(_startRewritingFromCandidateBar), @encode(void), NULL, 0)
    && CWMethod(cls, NO, @selector(_startWritingToolsWithTool:prompt:sender:), @encode(void), args, 3)
    && CWMethod(cls, NO, @selector(_endWritingTools), @encode(void), NULL, 0)
    && CWMethod(cls, NO, @selector(_isWritingToolsActive), @encode(bool), NULL, 0)
    && CWMethod(cls, NO, @selector(_supportsWritingTools), @encode(bool), NULL, 0);
}

static void CWRefreshSession(void) {
  ClarifyPrivateWritingToolsSession *session = CWSession;
  if (!session) return;
  @try {
    UITextView *owner = session.textView;
    if (!CWResponderShape(object_getClass(owner))) return;
    bool active = [owner _isWritingToolsActive];
    if (active) session.observedActive = YES;
    if (!active && (session.observedActive || session.endRequested)) {
      UITextView *view = session.textView;
      if (view && objc_getAssociatedObject(view, CWSessionKey) == session)
        objc_setAssociatedObject(view, CWSessionKey, nil, OBJC_ASSOCIATION_RETAIN_NONATOMIC);
      CWSession = nil;
      CWLastEndState = session.endRequested ? @"end_confirmed" : @"inactive_after_active";
    }
  } @catch (__unused NSException *exception) {
    // Unknown lifecycle: retain the slot. Never infer cancellation from an error.
  }
}

static void CWObserveSession(ClarifyPrivateWritingToolsSession *session, NSUInteger generation) {
  dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(0.5 * NSEC_PER_SEC)), dispatch_get_main_queue(), ^{
    if (CWSession != session || session.observationGeneration != generation) return;
    CWRefreshSession();
    if (CWSession == session && NSProcessInfo.processInfo.systemUptime < session.deadline)
      CWObserveSession(session, generation);
    // After 30 seconds, stop polling. isBusy/open can still observe a known end.
    // An unconfirmed session keeps its slot; no overlapping request is allowed.
  });
}

static NSDictionary *CWLifecycle(void) {
  ClarifyPrivateWritingToolsSession *session = CWSession;
  id active = @"unavailable";
  @try {
    if (session && CWResponderShape(object_getClass(session.textView)))
      active = @([session.textView _isWritingToolsActive]);
  } @catch (__unused NSException *exception) { active = @"read_failed"; }
  return @{ @"sessionPresent": @(session != nil),
    @"observedActive": @(session.observedActive), @"endRequested": @(session.endRequested),
    @"responderActive": active, @"route": @"uikit_responder", @"lastEndState": CWLastEndState };
}

static NSDictionary<NSString *, id> *CWReply(NSString *code, NSString *error, NSString *diagnostics) {
  // No source, result, operation ID or exception text in diagnostics. This
  // rejected route produces no output (and therefore cannot exceed 8k output).
  return @{ @"text": @"", @"error": error, @"code": code,
            @"diagnostics": diagnostics, @"route": @"private_textcomposer" };
}

static NSString *CWExtendedRewriteTypes(void) {
  // objc4 exposes extended protocol encodings used by XPC. Read metadata only.
  // https://github.com/apple-oss-distributions/objc4/blob/fb265098298302243cd7eeaa1f63f0ba7786dd9a/runtime/objc-internal.h#L1252
  typedef const char *(*EncodingFunction)(Protocol *, SEL, BOOL, BOOL);
  EncodingFunction encoding = (EncodingFunction)dlsym(RTLD_DEFAULT, "_protocol_getMethodTypeEncoding");
  Protocol *protocol = objc_getProtocol("TCTextCompositionXPCProtocol");
  if (!encoding || !protocol) return @"unavailable";
  const char *types = encoding(protocol, NSSelectorFromString(@"rewriteWithString:range:rewritingType:options:with:"), YES, YES);
  if (!types) return @"unavailable";
  NSUInteger count = strnlen(types, 4096);
  return [[NSString alloc] initWithBytes:types length:count encoding:NSUTF8StringEncoding] ?: @"unreadable";
}

@implementation ClarifyPrivateWritingToolsBridge
+ (NSDictionary<NSString *, id> *)probe {
  if (!NSThread.isMainThread) return @{ @"code": @"main_thread_required" };
  @try {
    CWLoad();
    Class tc = NSClassFromString(@"TCTextCompositionAssistant");
    Class ui = NSClassFromString(@"WTWritingToolsController");
    SEL rewrite = NSSelectorFromString(@"requestRewritingOfAttributedString:range:rewritingType:options:completionHandler:");
    const char *args[] = { @encode(id), @encode(NSRange), @encode(id), @encode(id), "@?" };
    return @{ @"platformAvailable": @(CWPlatform()),
      @"textComposerLoaded": @(CWTextComposerHandle != NULL),
      @"writingToolsUILoaded": @(CWWritingToolsHandle != NULL),
      @"assistantClass": @(tc != Nil), @"controllerClass": @(ui != Nil),
      @"sharedAssistantSignature": @(CWMethod(tc, YES, NSSelectorFromString(@"sharedAssistant"), @encode(id), NULL, 0)),
      @"rewriteSelector": @(tc && class_getInstanceMethod(tc, rewrite) != NULL),
      @"rewriteOuterSignature": @(CWMethod(tc, NO, rewrite, @encode(void), args, 5)),
      @"callbackVerified": @NO, @"rewriteIdentifiersVerified": @NO,
      @"directAvailable": @NO, @"controllerSignatures": @(CWUIShape(ui)),
      @"extendedRewriteProtocol": CWExtendedRewriteTypes(),
      @"assistantRewriteEncoding": CWEncoding(tc, NO, rewrite),
      @"controllerAvailableEncoding": CWEncoding(ui, YES, @selector(isAvailable)),
      @"controllerInitEncoding": CWEncoding(ui, NO, @selector(initWithTool:prompt:)),
      @"controllerSourceEncoding": CWEncoding(ui, NO, @selector(setSourceResponder:sourceTextInput:)),
      @"controllerStartEncoding": CWEncoding(ui, NO, @selector(startWritingTools)),
      @"controllerActiveEncoding": CWEncoding(ui, NO, @selector(isWritingToolsActive)),
      @"controllerEndEncoding": CWEncoding(ui, NO, @selector(endWritingTools)),
      @"responderSignatures": @(CWResponderShape(UITextView.class)),
      @"responderStartEncoding": CWEncoding(UITextView.class, NO, @selector(_startWritingToolsWithTool:prompt:sender:)),
      @"responderRewriteEncoding": CWEncoding(UITextView.class, NO, @selector(_startRewritingFromCandidateBar)),
      @"responderEndEncoding": CWEncoding(UITextView.class, NO, @selector(_endWritingTools)),
      @"responderActiveEncoding": CWEncoding(UITextView.class, NO, @selector(_isWritingToolsActive)),
      @"lifecycle": CWLifecycle(),
      @"iOS": UIDevice.currentDevice.systemVersion,
      @"code": @"direct_contract_unverified" };
  } @catch (__unused NSException *exception) {
    return @{ @"code": @"probe_exception", @"directAvailable": @NO };
  }
}

+ (BOOL)isBusy {
  if (!NSThread.isMainThread) return YES;
  CWRefreshSession();
  return CWSession != nil;
}

+ (void)rewrite:(NSString *)source style:(NSString *)style operationID:(NSString *)operationID
     completion:(void (^)(NSDictionary<NSString *, id> *))completion {
  if (!NSThread.isMainThread) {
    dispatch_async(dispatch_get_main_queue(), ^{
      completion(CWReply(@"main_thread_required", @"Main thread required.", @"request_rejected"));
    });
    return;
  }
  long long tool = 0;
  NSDictionary *reply;
  if (source.length == 0 || source.length > 2000 || operationID.length == 0 || operationID.length > 128 || !CWStyle(style, &tool)) {
    reply = CWReply(@"invalid_input", @"Invalid private rewrite input.", @"request_rejected");
  } else if ([self isBusy]) {
    reply = CWReply(@"busy", @"A private writing session is still pending.", @"completion_unconfirmed");
  } else {
    // Runtime headers expose only `id /* block */`, not its argument contract.
    // They also do not establish rewritingType string constants. Never call the
    // assistant, synthesize a callback ABI, or borrow WTRequestedTool integers.
    // https://github.com/qingralf/iOS26-Runtime-Headers/blob/cbf1d4c4122f3c6807eba36693581882640e5c6c/PrivateFrameworks/TextComposer.framework/TCTextCompositionAssistant.h
    NSDictionary *probe = [self probe];
    NSData *data = [NSJSONSerialization dataWithJSONObject:probe options:NSJSONWritingSortedKeys error:nil];
    NSString *metadata = data ? [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding] : @"probe_unavailable";
    reply = CWReply(@"direct_contract_unverified", @"The direct route is an interface check in this build. No rewrite was started.", metadata);
  }
  // Synchronous rejection has no in-flight work, late callback, timeout, retry
  // or fallback. Keep source unchanged; the caller retains its original draft.
  completion(reply);
}

+ (void)cancelOperation:(NSString *)operationID {
  if (!NSThread.isMainThread) return;
  (void)operationID;
  // No direct request can start. Do not cancel UI owned by a different contract
  // or clear an uncertain session slot without evidence that it has finished.
}

+ (BOOL)openToolForTextView:(UITextView *)textView style:(NSString *)style
               diagnostics:(NSString * __autoreleasing *)diagnostics {
  if (diagnostics) *diagnostics = @"ui_request_rejected";
  if (!NSThread.isMainThread) {
    if (diagnostics) *diagnostics = @"main_thread_required";
    return NO;
  }
  @try {
    long long tool = 0;
    if (!CWPlatform() || !CWStyle(style, &tool) || !textView.window || !textView.editable
        || textView.text.length == 0 || textView.text.length > 2000
        || UIApplication.sharedApplication.applicationState != UIApplicationStateActive) return NO;
    if ([self isBusy]) {
      if (diagnostics) *diagnostics = @"busy;completion_unconfirmed";
      return NO;
    }
    CWLoad();
    if (!CWResponderShape(object_getClass(textView))) {
      if (diagnostics) *diagnostics = @"responder_signature_unavailable";
      return NO;
    }
    if (![textView becomeFirstResponder] || ![textView _supportsWritingTools]) {
      if (diagnostics) *diagnostics = @"responder_unavailable";
      return NO;
    }
    if ([textView _isWritingToolsActive]) {
      if (diagnostics) *diagnostics = @"responder_already_active";
      return NO;
    }
    ClarifyPrivateWritingToolsSession *session = [ClarifyPrivateWritingToolsSession new];
    session.textView = textView;
    session.deadline = NSProcessInfo.processInfo.systemUptime + 30.0;
    CWSession = session;
    objc_setAssociatedObject(textView, CWSessionKey, session, OBJC_ASSOCIATION_RETAIN_NONATOMIC);
    // Retain before invocation, including when start throws after side effects.
    CWLastEndState = @"none";
    CWObserveSession(session, ++session.observationGeneration);
    if ([style isEqualToString:@"default"]) [textView _startRewritingFromCandidateBar];
    else {
      // These are responder NSString tool identifiers, not numeric WTRequestedTool.
      NSString *identifier = [style isEqualToString:@"formal"] ?
        @"WTUIRequestedToolRewriteProfessional" : @"WTUIRequestedToolRewriteFriendly";
      [textView _startWritingToolsWithTool:identifier prompt:nil sender:nil];
    }
    CWRefreshSession();
    if (diagnostics) *diagnostics = @"responder_start_requested;rewrite_unconfirmed";
    return YES;
  } @catch (__unused NSException *exception) {
    if (diagnostics) *diagnostics = @"ui_exception;result_unconfirmed";
    return NO;
  }
}

+ (void)endToolForTextView:(UITextView *)textView {
  if (!NSThread.isMainThread || CWSession.textView != textView) return;
  ClarifyPrivateWritingToolsSession *session = CWSession;
  if (session.endRequested) { CWRefreshSession(); return; }
  @try {
    if (CWResponderShape(object_getClass(textView))) {
      [textView _endWritingTools];
      // Apple can finish ending asynchronously, including a session whose active
      // state was never observed. Keep exclusion until inactivity is confirmed.
      if (CWSession == session) {
        session.endRequested = YES;
        CWLastEndState = @"end_requested";
        session.deadline = NSProcessInfo.processInfo.systemUptime + 30.0;
        CWRefreshSession();
        if (CWSession == session) CWObserveSession(session, ++session.observationGeneration);
      }
    } else { CWLastEndState = @"end_signature_unavailable"; }
  } @catch (__unused NSException *exception) {
    CWLastEndState = @"end_exception"; // Keep an uncertain session occupied.
  }
}
@end
