#import <XCTest/XCTest.h>
#import <React/RCTTextInputComponentView.h>
#import <react/renderer/textlayoutmanager/RCTAttributedTextUtils.h>
#include <react/renderer/components/textinput/TextInputState.h>
#include <react/renderer/core/ShadowNodeFamily.h>
#include <react/renderer/core/ConcreteState.h>

using namespace facebook::react;

@interface RCTTextInputComponentView (ClarifyTestAccess)
- (void)_setAttributedString:(NSAttributedString *)text;
- (void)textInputDidChange;
@end

@interface CountedTextInput : RCTTextInputComponentView
@property(nonatomic) NSUInteger textWrites;
@end
@implementation CountedTextInput
- (void)_setAttributedString:(NSAttributedString *)text
{
  self.textWrites += 1;
  [super _setAttributedString:text];
}
@end

static State::Shared StateFor(AttributedStringBox box, int64_t count)
{
  auto data = std::make_shared<TextInputState>();
  data->attributedStringBox = std::move(box);
  data->mostRecentEventCount = count;
  return std::make_shared<ConcreteState<TextInputState>>(data, ShadowNodeFamily::Weak{});
}

static State::Shared NativeState(NSString *text, int64_t count)
{
  return StateFor(RCTAttributedStringBoxFromNSAttributedString([[NSAttributedString alloc] initWithString:text]), count);
}

static State::Shared ReactState(const std::string &text, Float size, int64_t count)
{
  TextAttributes attributes;
  attributes.fontSize = size;
  AttributedString value;
  value.setBaseTextAttributes(attributes);
  value.appendFragment({.string = text, .textAttributes = attributes, .parentShadowView = {}});
  return StateFor(AttributedStringBox{value}, count);
}

@interface ClarifyTextInputTests : XCTestCase
@end
@implementation ClarifyTextInputTests
- (void)onMain:(dispatch_block_t)work
{
  if (NSThread.isMainThread) work();
  else dispatch_sync(dispatch_get_main_queue(), work);
}
- (UITextField *)fieldIn:(CountedTextInput *)input
{
  for (UIView *view in input.subviews) if ([view isKindOfClass:UITextField.class]) return (UITextField *)view;
  XCTFail(@"The real Fabric input must contain its native text field");
  return nil;
}
- (void)testInitialNativeRestoration
{
  [self onMain:^{
    CountedTextInput *input = [[CountedTextInput alloc] initWithFrame:CGRectMake(0, 0, 320, 48)];
    auto initial = NativeState(@"Restored draft", 3);
    [input updateState:initial oldState:State::Shared{}];
    XCTAssertEqualObjects([self fieldIn:input].text, @"Restored draft");
    XCTAssertEqual(input.textWrites, 1u);
  }];
}
- (void)testNativeAcknowledgementPreservesNewerText
{
  [self onMain:^{
    CountedTextInput *input = [[CountedTextInput alloc] initWithFrame:CGRectMake(0, 0, 320, 48)];
    auto initial = ReactState("", 16, 0);
    [input updateState:initial oldState:State::Shared{}];
    UITextField *field = [self fieldIn:input];
    field.attributedText = [[NSAttributedString alloc] initWithString:@"F"];
    [input textInputDidChange];
    auto acknowledgement = NativeState(@"F", 1);
    // UIKit can accept further edits inside a programmatic setter without
    // delivering another Fabric event. This is the captured failure pattern.
    field.attributedText = [[NSAttributedString alloc] initWithString:@"Fixture"];
    input.textWrites = 0;
    [input updateState:acknowledgement oldState:initial];
    XCTAssertEqualObjects(field.text, @"Fixture");
    XCTAssertEqual(input.textWrites, 0u, @"Native acknowledgements must not enter a text setter");
  }];
}
- (void)testDeclarativeTextAndStyleUpdates
{
  [self onMain:^{
    CountedTextInput *input = [[CountedTextInput alloc] initWithFrame:CGRectMake(0, 0, 320, 48)];
    auto initial = ReactState("seed", 16, 0);
    [input updateState:initial oldState:State::Shared{}];
    auto changed = ReactState("Updated", 24, 0);
    [input updateState:changed oldState:initial];
    UITextField *field = [self fieldIn:input];
    XCTAssertEqualObjects(field.text, @"Updated");
    UIFont *font = [field.attributedText attribute:NSFontAttributeName atIndex:0 effectiveRange:nullptr];
    XCTAssertEqualWithAccuracy(font.pointSize, 24, 0.1);
    auto styled = ReactState("Updated", 30, 0);
    [input updateState:styled oldState:changed];
    font = [field.attributedText attribute:NSFontAttributeName atIndex:0 effectiveRange:nullptr];
    XCTAssertEqualWithAccuracy(font.pointSize, 30, 0.1, @"Same-text styling must still apply");
  }];
}
- (void)testStaleStateSelectionAndExplicitClear
{
  [self onMain:^{
    CountedTextInput *input = [[CountedTextInput alloc] initWithFrame:CGRectMake(0, 0, 320, 48)];
    auto initial = ReactState("seed", 16, 0);
    [input updateState:initial oldState:State::Shared{}];
    UITextField *field = [self fieldIn:input];
    field.attributedText = [[NSAttributedString alloc] initWithString:@"Current"];
    [input textInputDidChange];
    auto stale = ReactState("stale", 16, 0);
    [input updateState:stale oldState:initial];
    XCTAssertEqualObjects(field.text, @"Current");
    [input handleCommand:@"setTextAndSelection" args:@[@1, @"Selected", @2, @4]];
    XCTAssertEqualObjects(field.text, @"Selected");
    XCTAssertEqual([field offsetFromPosition:field.beginningOfDocument toPosition:field.selectedTextRange.start], 2);
    XCTAssertEqual([field offsetFromPosition:field.beginningOfDocument toPosition:field.selectedTextRange.end], 4);
    [input handleCommand:@"setTextAndSelection" args:@[@1, @"", @0, @0]];
    XCTAssertEqualObjects(field.text, @"");
  }];
}
@end
