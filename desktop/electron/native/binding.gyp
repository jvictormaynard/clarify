{
  "targets": [{
    "target_name": "passive_window",
    "sources": ["passive_window.cc"],
    "defines": ["NAPI_VERSION=8"],
    "win_delay_load_hook": "false",
    "libraries": ["comctl32.lib", "user32.lib", "delayimp.lib"],
    "msvs_settings": {
      "VCCLCompilerTool": {"ExceptionHandling": 1, "AdditionalOptions": ["/std:c++17"]},
      "VCLinkerTool": {"DelayLoadDLLs": ["node.exe"]}
    }
  }]
}
