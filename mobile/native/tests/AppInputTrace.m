// Temporary instrumentation linked only into the isolated app UI fixture.
#import <UIKit/UIKit.h>
#import <objc/runtime.h>
#import <stdio.h>

static NSString *TracePath;
static NSUInteger Sequence;

static BOOL Target(UITextField *field) {
  return [field.placeholder isEqualToString:@"Nome ou termo"];
}

static NSDictionary *Snapshot(UITextField *field) {
  UITextRange *selection = field.selectedTextRange;
  return @{@"identity": [NSString stringWithFormat:@"%p", field],
    @"text": field.text ?: @"", @"enabled": @(field.enabled),
    @"focused": @(field.isFirstResponder),
    @"selection": selection ? @[@([field offsetFromPosition:field.beginningOfDocument toPosition:selection.start]),
      @([field offsetFromPosition:field.beginningOfDocument toPosition:selection.end])] : @[]};
}

static void Trace(NSString *event, NSDictionary *values) {
  if (!TracePath) return;
  NSMutableDictionary *record = [values mutableCopy];
  record[@"event"] = event; record[@"sequence"] = @(++Sequence);
  record[@"pid"] = @(NSProcessInfo.processInfo.processIdentifier);
  record[@"uptime"] = @(NSProcessInfo.processInfo.systemUptime);
  NSData *data = [NSJSONSerialization dataWithJSONObject:record options:0 error:nil];
  if (!data) return;
  FILE *file = fopen(TracePath.fileSystemRepresentation, "ab");
  if (file) { fwrite(data.bytes, 1, data.length, file); fputc('\n', file); fclose(file); }
}

static BOOL Hook(Class cls, SEL selector, IMP (^wrap)(IMP)) {
  if (!cls) return NO;
  Method method = class_getInstanceMethod(cls, selector);
  if (!method) return NO;
  IMP replacement = wrap(method_getImplementation(method));
  if (!class_addMethod(cls, selector, replacement, method_getTypeEncoding(method))) {
    method_setImplementation(method, replacement);
  }
  return YES;
}

static void Install(void) {
  NSURL *endpoint = [NSURL URLWithString:[NSBundle.mainBundle objectForInfoDictionaryKey:@"ClarifyCloudURL"] ?: @""];
  if (![endpoint.scheme isEqualToString:@"http"] || ![@[@"127.0.0.1", @"localhost"] containsObject:endpoint.host]) return;
  TracePath = [NSSearchPathForDirectoriesInDomains(NSCachesDirectory, NSUserDomainMask, YES).firstObject
    stringByAppendingPathComponent:@"clarify-input-trace.jsonl"];
  Class adapter = NSClassFromString(@"RCTBackedTextFieldDelegateAdapter");
  SEL change = NSSelectorFromString(@"textField:shouldChangeCharactersInRange:replacementString:");
  BOOL replacements = Hook(adapter, change, ^IMP(IMP original) {
    return imp_implementationWithBlock(^BOOL(id owner, UITextField *field, NSRange range, NSString *text) {
      BOOL target = Target(field);
      if (target) Trace(@"replace-before", @{@"field": Snapshot(field), @"range": @[@(range.location), @(range.length)], @"replacement": text ?: @""});
      BOOL accepted = ((BOOL (*)(id, SEL, UITextField *, NSRange, NSString *))original)(owner, change, field, range, text);
      if (target) Trace(@"replace-return", @{@"field": Snapshot(field), @"accepted": @(accepted)});
      return accepted;
    });
  });
  Class fieldClass = NSClassFromString(@"RCTUITextField");
  SEL attributed = @selector(setAttributedText:);
  BOOL writes = Hook(fieldClass, attributed, ^IMP(IMP original) {
    return imp_implementationWithBlock(^(UITextField *field, NSAttributedString *value) {
      BOOL target = Target(field);
      if (target) Trace(@"attributed-before", @{@"field": Snapshot(field), @"incoming": value.string ?: @"",
        @"stack": [NSThread.callStackSymbols subarrayWithRange:NSMakeRange(0, MIN(10, NSThread.callStackSymbols.count))]});
      ((void (*)(id, SEL, NSAttributedString *))original)(field, attributed, value);
      if (target) Trace(@"attributed-after", @{@"field": Snapshot(field)});
    });
  });
  SEL enabled = @selector(setEnabled:);
  BOOL enabledChanges = Hook(fieldClass, enabled, ^IMP(IMP original) {
    return imp_implementationWithBlock(^(UITextField *field, BOOL value) {
      if (Target(field) && field.enabled != value) Trace(@"enabled", @{@"field": Snapshot(field), @"incoming": @(value)});
      ((void (*)(id, SEL, BOOL))original)(field, enabled, value);
    });
  });
  for (NSNotificationName name in @[UITextFieldTextDidBeginEditingNotification, UITextFieldTextDidEndEditingNotification, UITextFieldTextDidChangeNotification]) {
    [NSNotificationCenter.defaultCenter addObserverForName:name object:nil queue:nil usingBlock:^(NSNotification *note) {
      UITextField *field = [note.object isKindOfClass:UITextField.class] ? note.object : nil;
      if (field && Target(field)) Trace(name, @{@"field": Snapshot(field)});
    }];
  }
  Trace(@"installed", @{@"replacements": @(replacements), @"attributedWrites": @(writes), @"enabledChanges": @(enabledChanges)});
}

__attribute__((constructor)) static void PrepareInputTrace(void) {
  [NSNotificationCenter.defaultCenter addObserverForName:UIApplicationDidFinishLaunchingNotification object:nil
    queue:NSOperationQueue.mainQueue usingBlock:^(__unused NSNotification *note) { Install(); }];
}
