#import "ClarifyPrivateWritingToolsBridge.h"
#import <objc/runtime.h>
#import <dlfcn.h>
#import <TargetConditionals.h>
#import <stdbool.h>
#import <stdlib.h>
#import <string.h>
#import <limits.h>

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
+ (id)sharedAssistant;
- (id)initWithAttributedString:(id)text range:(NSRange)range options:(id)options error:(NSError **)error;
- (void)rewriteWithInput:(id)input rewritingType:(id)type with:(void (^)(id, NSError *))completion;
- (void)cancelWithToken:(long long)token;
- (void)requestCancellationForToken:(unsigned long long)token cancelModelInvocations:(bool)cancel;
- (id)rewrittenString;
@end

static void *CWTextComposerHandle;
static void *CWWritingToolsHandle;

@interface ClarifyPrivateWritingToolsSession : NSObject
// Keep the responder alive through asynchronous end. The global session is the
// sole bridge owner; no associated-object back-reference creates a retain cycle.
@property (nonatomic, strong) UITextView *textView;
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

// Direct requests never create UIKit views. Callback object types correspond to
// TCTextCompositionXPCProtocol rewriteWithInput:rewritingType:with: in iOS 26.
// Its conforming service worker is instantiated directly; no wrapper callback
// is inferred, no connection identity is forged, and no Apple UI is created.
// https://github.com/qingralf/iOS26-Runtime-Headers/blob/cbf1d4c4122f3c6807eba36693581882640e5c6c/PrivateFrameworks/TextComposer.framework/_TtCC12TextComposer26TCTextCompositionXPCServer6Server.h
// https://github.com/qingralf/iOS26-Runtime-Headers/blob/cbf1d4c4122f3c6807eba36693581882640e5c6c/protocols/TCTextCompositionXPCProtocol.h
@interface ClarifyDirectRewriteSession : NSObject
@property (nonatomic, copy) NSString *operationID;
@property (nonatomic, strong) id assistant;
@property (nonatomic, strong) id input;
@property (nonatomic) unsigned long long token;
@property (nonatomic, copy) void (^completion)(NSDictionary *);
@end
@implementation ClarifyDirectRewriteSession
@end
static ClarifyDirectRewriteSession *CWDirect;

// Resolve actual exported NSString values, never guessed literal names or UI enums.
// https://github.com/xybp888/iOS-SDKs/blob/1b92ff4a8928f582876e1d388d1381c6a0c59eb9/iPhoneOS26.5.sdk/System/Library/PrivateFrameworks/TextComposer.framework/TextComposer.tbd
static NSString *CWConstant(const char *symbol) {
  if (!CWTextComposerHandle) return nil;
  NSString * __unsafe_unretained *address = (NSString * __unsafe_unretained *)dlsym(CWTextComposerHandle, symbol);
  id value = address ? *address : nil;
  return [value isKindOfClass:NSString.class] ? value : nil;
}
static NSString *CWRewriteType(NSString *style) {
  if ([style isEqualToString:@"default"]) return CWConstant("TCTextCompositionAssistantRewritingTypeMagic");
  if ([style isEqualToString:@"formal"]) return CWConstant("TCTextCompositionAssistantRewritingTypeProfessional");
  if ([style isEqualToString:@"casual"]) return CWConstant("TCTextCompositionAssistantRewritingTypeFriendly");
  return nil;
}


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
  return CWSession != nil || CWDirect != nil;
}

+ (void)rewrite:(NSString *)source style:(NSString *)style operationID:(NSString *)operationID
     completion:(void (^)(NSDictionary<NSString *, id> *))completion {
  if (!NSThread.isMainThread) {
    dispatch_async(dispatch_get_main_queue(), ^{ completion(CWReply(@"main_thread_required", @"Apple rewriting could not start. The transcript was preserved.", @"request_rejected")); });
    return;
  }
  if (source.length == 0 || [source lengthOfBytesUsingEncoding:NSUTF8StringEncoding] > 2000 || operationID.length == 0 || operationID.length > 128) {
    completion(CWReply(@"invalid_input", @"Use a shorter recording for Apple rewriting. The transcript was preserved.", @"request_rejected")); return;
  }
  if ([self isBusy]) {
    completion(CWReply(@"busy", @"Apple rewriting is still finishing an earlier request. The transcript was preserved.", @"request_rejected")); return;
  }
  @try {
    CWLoad();
    Class assistantClass = NSClassFromString(@"_TtCC12TextComposer26TCTextCompositionXPCServer6Server");
    Protocol *serviceProtocol = objc_getProtocol("TCTextCompositionXPCProtocol");
    Class inputClass = NSClassFromString(@"TCTextCompositionInput");
    const char *requestArgs[] = { @encode(id), @encode(id), "@?" };
    const char *inputArgs[] = { @encode(id), @encode(NSRange), @encode(id), @encode(NSError **) };
    const char *cancelArgs[] = { @encode(long long) };
    NSString *type = CWRewriteType(style);
    NSString *tokenKey = CWConstant("TCTextCompositionAssistantOptionKeyToken");
    if (!CWPlatform() || !type || !tokenKey || !serviceProtocol || !class_conformsToProtocol(assistantClass, serviceProtocol)
        || !CWMethod(assistantClass, NO, @selector(init), @encode(id), NULL, 0)
        || !CWMethod(inputClass, NO, @selector(initWithAttributedString:range:options:error:), @encode(id), inputArgs, 4)
        || !CWMethod(assistantClass, NO, @selector(rewriteWithInput:rewritingType:with:), @encode(void), requestArgs, 3)
        || !CWMethod(assistantClass, NO, @selector(cancelWithToken:), @encode(void), cancelArgs, 1)) {
      completion(CWReply(@"service_contract_unavailable", @"The direct Apple rewrite service is unavailable on this iPhone. The transcript was preserved.", @"runtime_contract_rejected")); return;
    }
    id assistant = [[assistantClass alloc] init];
    if (!assistant || object_getClass(assistant) != assistantClass) {
      completion(CWReply(@"service_unavailable", @"Apple rewriting could not start. The transcript was preserved.", @"assistant_unavailable")); return;
    }
    ClarifyDirectRewriteSession *session = [ClarifyDirectRewriteSession new];
    session.operationID = operationID; session.assistant = assistant;
    session.token = ((((unsigned long long)arc4random() << 32) | arc4random()) & LLONG_MAX);
    NSError *error = nil;
    session.input = [[inputClass alloc] initWithAttributedString:[[NSAttributedString alloc] initWithString:source]
      range:NSMakeRange(0, source.length) options:@{tokenKey: @(session.token)} error:&error];
    if (!session.input || error) {
      completion(CWReply(@"input_rejected", @"Apple could not prepare this text for rewriting. The transcript was preserved.", @"input_rejected")); return;
    }
    session.completion = completion;
    CWDirect = session;
    [assistant rewriteWithInput:session.input rewritingType:type with:^(id output, NSError *serviceError) {
      dispatch_async(dispatch_get_main_queue(), ^{
        if (CWDirect != session) return;
        void (^reply)(NSDictionary *) = session.completion;
        session.completion = nil; CWDirect = nil;
        if (!reply) return; // Cancelled or timed out. Never publish late text.
        @try {
          Class outputClass = NSClassFromString(@"TCTextCompositionOutput");
          if (serviceError || !outputClass || ![output isKindOfClass:outputClass]
              || !CWMethod(object_getClass(output), NO, @selector(rewrittenString), @encode(id), NULL, 0)) {
            reply(CWReply(@"service_failed", @"Apple rewriting failed. The transcript was preserved.", @"service_callback_rejected")); return;
          }
          id text = [output rewrittenString];
          if (![text isKindOfClass:NSString.class] || [text length] == 0 || [text lengthOfBytesUsingEncoding:NSUTF8StringEncoding] > 8000) {
            reply(CWReply(@"invalid_output", @"Apple returned an invalid rewrite. The transcript was preserved.", @"output_rejected")); return;
          }
          reply(@{@"text": text, @"error": @"", @"code": @"ok", @"route": @"private_textcomposer", @"diagnostics": @"direct_service_completed"});
        } @catch (__unused NSException *exception) {
          reply(CWReply(@"callback_failed", @"Apple rewriting failed. The transcript was preserved.", @"callback_exception"));
        }
      });
    }];
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(30 * NSEC_PER_SEC)), dispatch_get_main_queue(), ^{
      if (CWDirect != session || !session.completion) return;
      void (^reply)(NSDictionary *) = session.completion; session.completion = nil;
      @try { [session.assistant cancelWithToken:(long long)session.token]; }
      @catch (__unused NSException *exception) {}
      // Keep the slot until its callback confirms the service request ended.
      reply(CWReply(@"service_timeout", @"Apple rewriting took too long. The transcript was preserved.", @"cancellation_requested"));
    });
  } @catch (__unused NSException *exception) {
    if (CWDirect) {
      CWDirect.completion = nil; // Unknown service state: keep its slot.
    }
    completion(CWReply(@"service_exception", @"Apple rewriting could not run. The transcript was preserved.", @"service_exception"));
  }
}

+ (void)cancelOperation:(NSString *)operationID {
  if (!NSThread.isMainThread || ![CWDirect.operationID isEqualToString:operationID]) return;
  ClarifyDirectRewriteSession *session = CWDirect;
  void (^reply)(NSDictionary *) = session.completion; session.completion = nil;
  @try { [session.assistant cancelWithToken:(long long)session.token]; }
  @catch (__unused NSException *exception) {}
  if (reply) reply(CWReply(@"cancelled", @"Apple rewriting was cancelled.", @"cancellation_requested"));
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
