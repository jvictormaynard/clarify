{
  "targets": [{
    "target_name": "passive_window",
    "defines": ["NAPI_VERSION=8"],
    "conditions": [
      ["OS=='win'", {
        "sources": ["passive_window.cc"],
        "win_delay_load_hook": "false",
        "libraries": ["comctl32.lib", "user32.lib", "delayimp.lib"],
        "msvs_settings": {
          "VCCLCompilerTool": {"ExceptionHandling": 1, "AdditionalOptions": ["/std:c++17"]},
          "VCLinkerTool": {"DelayLoadDLLs": ["node.exe"]}
        }
      }],
      ["OS=='mac'", {
        "target_name": "mac_work_area",
        "sources": ["mac_work_area.mm"],
        "libraries": ["-framework AppKit", "-framework CoreGraphics"]
      }]
    ]
  }]
}
