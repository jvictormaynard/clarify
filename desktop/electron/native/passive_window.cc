#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <commctrl.h>
#include <delayimp.h>
#include <node_api.h>
#include <cstring>

static LRESULT CALLBACK PassiveProc(HWND hwnd, UINT message, WPARAM wparam,
                                    LPARAM lparam, UINT_PTR id, DWORD_PTR) {
  if (message == WM_MOUSEACTIVATE) return MA_NOACTIVATE;
  if (message == WM_NCDESTROY) RemoveWindowSubclass(hwnd, PassiveProc, id);
  return DefSubclassProc(hwnd, message, wparam, lparam);
}

static napi_value Fail(napi_env env, const char* message) {
  napi_throw_error(env, nullptr, message);
  return nullptr;
}

static napi_value SetPassive(napi_env env, napi_callback_info info) {
  size_t count = 2;
  napi_value args[2];
  if (napi_get_cb_info(env, info, &count, args, nullptr, nullptr) != napi_ok || count != 2)
    return Fail(env, "Expected HWND buffer and passive boolean");
  bool buffer = false, passive = false;
  void* bytes = nullptr;
  size_t length = 0;
  if (napi_is_buffer(env, args[0], &buffer) != napi_ok || !buffer ||
      napi_get_buffer_info(env, args[0], &bytes, &length) != napi_ok || length != sizeof(HWND) ||
      napi_get_value_bool(env, args[1], &passive) != napi_ok)
    return Fail(env, "Invalid HWND buffer or passive boolean");
  HWND hwnd = nullptr;
  std::memcpy(&hwnd, bytes, sizeof(hwnd));
  DWORD pid = 0;
  DWORD thread = GetWindowThreadProcessId(hwnd, &pid);
  if (!IsWindow(hwnd) || pid != GetCurrentProcessId() || thread != GetCurrentThreadId())
    return Fail(env, "HWND must belong to this process and UI thread");
  const UINT_PTR id = reinterpret_cast<UINT_PTR>(PassiveProc);
  DWORD_PTR data = 0;
  bool installed = GetWindowSubclass(hwnd, PassiveProc, id, &data) != FALSE;
  if (passive && !installed && !SetWindowSubclass(hwnd, PassiveProc, id, 0))
    return Fail(env, "SetWindowSubclass failed");
  if (!passive && installed && !RemoveWindowSubclass(hwnd, PassiveProc, id))
    return Fail(env, "RemoveWindowSubclass failed");
  napi_value result;
  napi_get_boolean(env, true, &result);
  return result;
}

static napi_value Init(napi_env env, napi_value exports) {
  napi_value function;
  if (napi_create_function(env, "setPassive", NAPI_AUTO_LENGTH, SetPassive, nullptr, &function) != napi_ok ||
      napi_set_named_property(env, exports, "setPassive", function) != napi_ok)
    return Fail(env, "Cannot export setPassive");
  return exports;
}
NAPI_MODULE(passive_window, Init)

// Cached Node import library uses node.exe. Electron exports the same stable N-API.
static FARPROC WINAPI DelayHook(unsigned event, PDelayLoadInfo info) {
  if (event == dliNotePreLoadLibrary && std::strcmp(info->szDll, "node.exe") == 0)
    return reinterpret_cast<FARPROC>(GetModuleHandleW(nullptr));
  return nullptr;
}
extern "C" const PfnDliHook __pfnDliNotifyHook2 = DelayHook;
