#import <AppKit/AppKit.h>
#import <CoreGraphics/CoreGraphics.h>
#include <cmath>
#include <node_api.h>

static napi_value JsBounds(napi_env env, CGRect bounds) {
  napi_value result;
  napi_create_object(env, &result);
  const char* keys[] = {"x", "y", "width", "height"};
  const double values[] = {
      CGRectGetMinX(bounds), CGRectGetMinY(bounds),
      CGRectGetWidth(bounds), CGRectGetHeight(bounds)};
  for (size_t i = 0; i < 4; ++i) {
    napi_value value;
    napi_create_double(env, values[i], &value);
    napi_set_named_property(env, result, keys[i], value);
  }
  return result;
}

static napi_value GetSystemSettingsBounds(napi_env env, napi_callback_info) {
  @autoreleasepool {
    NSRunningApplication* foreground = NSWorkspace.sharedWorkspace.frontmostApplication;
    if ([foreground.bundleIdentifier isEqualToString:@"com.apple.systempreferences"]) {
      // Window geometry is available before any privacy grants. No window pixels are read.
      CFArrayRef windows = CGWindowListCopyWindowInfo(
          kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements,
          kCGNullWindowID);
      if (windows) {
        for (NSDictionary* window in (__bridge NSArray*)windows) {
          if ([window[(__bridge NSString*)kCGWindowOwnerPID] intValue] != foreground.processIdentifier ||
              [window[(__bridge NSString*)kCGWindowLayer] intValue] != 0)
            continue;
          CGRect bounds;
          NSDictionary* geometry = window[(__bridge NSString*)kCGWindowBounds];
          if (geometry &&
              CGRectMakeWithDictionaryRepresentation((__bridge CFDictionaryRef)geometry, &bounds) &&
              CGRectGetWidth(bounds) >= 400 && CGRectGetHeight(bounds) >= 300) {
            CFRelease(windows);
            return JsBounds(env, bounds);
          }
        }
        CFRelease(windows);
      }
    }
  }
  napi_value result;
  napi_get_undefined(env, &result);
  return result;
}

static bool VisibleWindowFillsScreen(NSScreen* screen, double primary_top) {
  NSRect frame = screen.frame;
  CGFloat top = primary_top - NSMaxY(frame);
  // A fullscreen Space can stay visible when the pill or another display has focus.
  // Match the window to this display, including the notch.
  CFArrayRef windows = CGWindowListCopyWindowInfo(
      kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements,
      kCGNullWindowID);
  if (!windows)
    return false;
  bool fills_screen = false;
  for (NSDictionary* window in (__bridge NSArray*)windows) {
    if ([window[(__bridge NSString*)kCGWindowLayer] intValue] != 0)
      continue;
    CGRect bounds;
    NSDictionary* geometry = window[(__bridge NSString*)kCGWindowBounds];
    if (geometry &&
        CGRectMakeWithDictionaryRepresentation((__bridge CFDictionaryRef)geometry, &bounds) &&
        std::abs(CGRectGetMinX(bounds) - NSMinX(frame)) <= 1 &&
        std::abs(CGRectGetMaxX(bounds) - NSMaxX(frame)) <= 1 &&
        std::abs(CGRectGetMaxY(bounds) - (top + NSHeight(frame))) <= 1 &&
        CGRectGetMinY(bounds) >= top - 1 &&
        CGRectGetMinY(bounds) <= top + screen.safeAreaInsets.top + 1) {
      fills_screen = true;
      break;
    }
  }
  CFRelease(windows);
  return fills_screen;
}

static napi_value GetWorkArea(napi_env env, napi_callback_info info) {
  size_t count = 1;
  napi_value arg;
  uint32_t display_id;
  if (napi_get_cb_info(env, info, &count, &arg, nullptr, nullptr) != napi_ok ||
      count != 1 || napi_get_value_uint32(env, arg, &display_id) != napi_ok) {
    napi_throw_type_error(env, nullptr, "Expected a display ID");
    return nullptr;
  }

  @autoreleasepool {
    NSArray<NSScreen*>* screens = [NSScreen screens];
    for (NSScreen* screen in screens) {
      NSNumber* screen_number = screen.deviceDescription[@"NSScreenNumber"];
      if (screen_number.unsignedIntValue != display_id)
        continue;

      double primary_top = NSMaxY(screens.firstObject.frame);
      NSRect area = screen.visibleFrame;
      if (!NSEqualRects(area, screen.frame) && VisibleWindowFillsScreen(screen, primary_top))
        area = screen.frame;
      // AppKit uses a bottom-left origin. Electron uses the primary screen's top-left.
      double top = primary_top - NSMaxY(area);
      return JsBounds(env, CGRectMake(NSMinX(area), top, NSWidth(area), NSHeight(area)));
    }
  }

  // A display may disappear before Electron refreshes its display list.
  napi_value result;
  napi_get_undefined(env, &result);
  return result;
}

static napi_value Init(napi_env env, napi_value exports) {
  napi_value function;
  napi_create_function(env, "getWorkArea", NAPI_AUTO_LENGTH, GetWorkArea, nullptr, &function);
  napi_set_named_property(env, exports, "getWorkArea", function);
  napi_create_function(env, "getSystemSettingsBounds", NAPI_AUTO_LENGTH, GetSystemSettingsBounds,
                       nullptr, &function);
  napi_set_named_property(env, exports, "getSystemSettingsBounds", function);
  return exports;
}

NAPI_MODULE(mac_work_area, Init)
