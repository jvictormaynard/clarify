// Temporary instrumentation linked only into the isolated app UI fixture.
#import <UIKit/UIKit.h>
#import <objc/runtime.h>
#import <stdio.h>

static NSString *TracePath;
static NSUInteger Sequence;

static BOOL Target(id field) {
  return [field isKindOfClass:NSClassFromString(@"RCTUITextField")] ||
    [field isKindOfClass:NSClassFromString(@"RCTUITextView")];
}

static BOOL InputEnabled(UIView<UITextInput> *field) {
  return [field isKindOfClass:UITextView.class] ? [(UITextView *)field isEditable] : [(UITextField *)field isEnabled];
}

static NSDictionary *Snapshot(UIView<UITextInput> *field) {
  UITextRange *selection = field.selectedTextRange;
  return @{@"identity": [NSString stringWithFormat:@"%p", field],
    @"kind": NSStringFromClass(field.class), @"placeholder": [(id)field placeholder] ?: @"",
    @"identifier": field.accessibilityIdentifier ?: @"", @"label": field.accessibilityLabel ?: @"",
    @"text": [(id)field text] ?: @"", @"enabled": @(InputEnabled(field)),
    @"focused": @(field.isFirstResponder),
    @"selection": selection ? @[@([field offsetFromPosition:field.beginningOfDocument toPosition:selection.start]),
      @([field offsetFromPosition:field.beginningOfDocument toPosition:selection.end])] : @[]};
}

static void Trace(NSString *event, NSDictionary *values) {
  if (!TracePath) return;
  NSMutableDictionary *record = [values mutableCopy];
  record[@"event"] = event; record[@"sequence"] = @(++Sequence);
  record[@"pid"] = @(NSProcessInfo.processInfo.processIdentifier);
  record[@"mainThread"] = @(NSThread.isMainThread);
  record[@"thread"] = [NSString stringWithFormat:@"%p", NSThread.currentThread];
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

static NSDictionary *AttributeValues(NSDictionary *values) {
  NSMutableDictionary *result = [NSMutableDictionary dictionary];
  for (NSString *key in values) {
    id value = values[key];
    NSString *description = [value description] ?: @"";
    NSMutableDictionary *entry = [@{@"kind": NSStringFromClass([value class]),
      @"description": [description substringToIndex:MIN(2048, description.length)]} mutableCopy];
    if ([value isKindOfClass:NSData.class]) {
      NSData *bytes = value;
      entry[@"length"] = @(bytes.length);
      entry[@"bytesPrefix"] = [[bytes subdataWithRange:NSMakeRange(0, MIN(64, bytes.length))] base64EncodedStringWithOptions:0];
    }
    if ([value isKindOfClass:UIFont.class]) {
      UIFont *font = value;
      entry[@"fontName"] = font.fontName; entry[@"pointSize"] = @(font.pointSize);
      NSString *descriptor = font.fontDescriptor.fontAttributes.description ?: @"";
      entry[@"descriptor"] = [descriptor substringToIndex:MIN(2048, descriptor.length)];
    }
    result[key] = entry;
  }
  return result;
}

static NSArray *AttributeRuns(NSAttributedString *value) {
  NSMutableArray *runs = [NSMutableArray array];
  [value enumerateAttributesInRange:NSMakeRange(0, MIN(512, value.length)) options:0
    usingBlock:^(NSDictionary *attributes, NSRange range, __unused BOOL *stop) {
      [runs addObject:@{@"range": @[@(range.location), @(range.length)], @"values": AttributeValues(attributes)}];
    }];
  return runs;
}

static UIView<UITextInput> *FindInput(UIView *view) {
  if (Target(view)) return (UIView<UITextInput> *)view;
  for (UIView *child in view.subviews) {
    UIView<UITextInput> *found = FindInput(child);
    if (found) return found;
  }
  return nil;
}

static NSDictionary *OriginalTypingAttributes(id owner) {
  Ivar ivar = class_getInstanceVariable([owner class], "_originalTypingAttributes");
  const char *type = ivar ? ivar_getTypeEncoding(ivar) : NULL;
  if (!type || type[0] != '@') return @{@"unavailable": @YES};
  id value = object_getIvar(owner, ivar);
  return [value isKindOfClass:NSDictionary.class] ? AttributeValues(value) : @{@"unavailable": @YES};
}

static void Install(void) {
  NSURL *endpoint = [NSURL URLWithString:[NSBundle.mainBundle objectForInfoDictionaryKey:@"ClarifyCloudURL"] ?: @""];
  if (![endpoint.scheme isEqualToString:@"http"] || ![@[@"127.0.0.1", @"localhost"] containsObject:endpoint.host]) return;
  TracePath = [NSSearchPathForDirectoriesInDomains(NSCachesDirectory, NSUserDomainMask, YES).firstObject
    stringByAppendingPathComponent:@"clarify-input-trace.jsonl"];
  NSMutableDictionary *hooks = [NSMutableDictionary dictionary];
  SEL compare = NSSelectorFromString(@"_textOf:equals:");
  hooks[@"comparator"] = @(Hook(NSClassFromString(@"RCTTextInputComponentView"), compare, ^IMP(IMP original) {
    return imp_implementationWithBlock(^BOOL(id owner, NSAttributedString *incoming, NSAttributedString *current) {
      BOOL same = ((BOOL (*)(id, SEL, NSAttributedString *, NSAttributedString *))original)(owner, compare, incoming, current);
      if (!same && [incoming.string isEqualToString:current.string]) {
        UIView<UITextInput> *field = FindInput(owner);
        if (field) Trace(@"equal-text-attributes-differ", @{@"field": Snapshot(field),
          @"originalResult": @(same), @"incomingText": incoming.string ?: @"", @"currentText": current.string ?: @"",
          @"incomingRuns": AttributeRuns(incoming), @"currentRuns": AttributeRuns(current),
          @"originalTypingAttributes": OriginalTypingAttributes(owner),
          @"defaultTextAttributes": AttributeValues([(id)field defaultTextAttributes]),
          @"typingAttributes": AttributeValues([(id)field typingAttributes]),
          @"markedText": @(field.markedTextRange != nil), @"language": field.textInputMode.primaryLanguage ?: @""});
      }
      return same;
    });
  }));
  for (NSDictionary *config in @[
    @{@"adapter": @"RCTBackedTextFieldDelegateAdapter", @"input": @"RCTUITextField", @"prefix": @"single",
      @"change": @"textField:shouldChangeCharactersInRange:replacementString:", @"availability": @"setEnabled:"},
    @{@"adapter": @"RCTBackedTextViewDelegateAdapter", @"input": @"RCTUITextView", @"prefix": @"multi",
      @"change": @"textView:shouldChangeTextInRange:replacementText:", @"availability": @"setEditable:"}
  ]) {
    Class adapter = NSClassFromString(config[@"adapter"]);
    SEL change = NSSelectorFromString(config[@"change"]);
    BOOL replacements = Hook(adapter, change, ^IMP(IMP original) {
      return imp_implementationWithBlock(^BOOL(id owner, UIView<UITextInput> *field, NSRange range, NSString *text) {
        BOOL target = Target(field);
        if (target) Trace(@"replace-before", @{@"field": Snapshot(field), @"range": @[@(range.location), @(range.length)], @"replacement": text ?: @""});
        BOOL accepted = ((BOOL (*)(id, SEL, id, NSRange, NSString *))original)(owner, change, field, range, text);
        if (target) Trace(@"replace-return", @{@"field": Snapshot(field), @"accepted": @(accepted)});
        return accepted;
      });
    });
    Class input = NSClassFromString(config[@"input"]);
    SEL attributed = @selector(setAttributedText:);
    BOOL writes = Hook(input, attributed, ^IMP(IMP original) {
      return imp_implementationWithBlock(^(UIView<UITextInput> *field, NSAttributedString *value) {
        BOOL target = Target(field);
        if (target) {
          NSArray *stack = NSThread.callStackSymbols;
          Trace(@"attributed-before", @{@"field": Snapshot(field), @"incoming": value.string ?: @"",
            @"stack": [stack subarrayWithRange:NSMakeRange(0, MIN(10, stack.count))]});
        }
        ((void (*)(id, SEL, NSAttributedString *))original)(field, attributed, value);
        if (target) Trace(@"attributed-after", @{@"field": Snapshot(field)});
      });
    });
    SEL availability = NSSelectorFromString(config[@"availability"]);
    BOOL enabledChanges = Hook(input, availability, ^IMP(IMP original) {
      return imp_implementationWithBlock(^(UIView<UITextInput> *field, BOOL value) {
        if (Target(field) && InputEnabled(field) != value) Trace(@"enabled", @{@"field": Snapshot(field), @"incoming": @(value)});
        ((void (*)(id, SEL, BOOL))original)(field, availability, value);
      });
    });
    hooks[[config[@"prefix"] stringByAppendingString:@".replacements"]] = @(replacements);
    hooks[[config[@"prefix"] stringByAppendingString:@".writes"]] = @(writes);
    hooks[[config[@"prefix"] stringByAppendingString:@".availability"]] = @(enabledChanges);
  }
  for (NSNotificationName name in @[UITextFieldTextDidBeginEditingNotification, UITextFieldTextDidEndEditingNotification,
    UITextFieldTextDidChangeNotification, UITextViewTextDidBeginEditingNotification,
    UITextViewTextDidEndEditingNotification, UITextViewTextDidChangeNotification]) {
    [NSNotificationCenter.defaultCenter addObserverForName:name object:nil queue:nil usingBlock:^(NSNotification *note) {
      if (Target(note.object)) Trace(name, @{@"field": Snapshot(note.object)});
    }];
  }
  Trace(@"installed", hooks);
}

__attribute__((constructor)) static void PrepareInputTrace(void) {
  [NSNotificationCenter.defaultCenter addObserverForName:UIApplicationDidFinishLaunchingNotification object:nil
    queue:NSOperationQueue.mainQueue usingBlock:^(__unused NSNotification *note) { Install(); }];
}
