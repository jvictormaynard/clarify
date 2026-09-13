import QtQuick 6.5
import QtQuick.Controls 6.5
import QtQuick.Layouts 6.5

SearchSelect {
    id: picker
    objectName: "workflowModelPicker"
    required property var settingsController
    signal connectProvider()
    signal modelIdRequested()
    options: settingsController.routeModelOptions
    value: settingsController.routeModelId
    caption: "Choose a model"
    placeholderText: "Choose a model"
    searchPlaceholder: "Search models…"
    refreshable: settingsController.routeModelStatus !== "not_configured"
    busy: settingsController.routeModelStatus === "loading"
    secondaryActionText: settingsController.routeProviderId === "local_asr" ? ""
                        : settingsController.routeModelStatus === "not_configured"
                        || settingsController.routeModelStatus === "error" ? "Connect service" : "Use model ID…"
    statusText: {
        var status = settingsController.routeModelStatus
        if (settingsController.routeProviderId === "local_asr") {
            if (status === "loading") return "Checking installed models…"
            if (status === "empty") return "No installed models. Install one in Integrations."
            if (status === "error") return "Could not check local models. Try refresh."
        }
        if (status === "loading") return "Loading models…"
        if (status === "not_configured") return "Connect this service to browse its models."
        if (status === "error") return "Could not load models. Check the connection and retry."
        if (status === "empty") return "No compatible models returned by this service."
        return ""
    }
    function loadModels() { if (visible) settingsController.loadRouteModels() }
    onVisibleChanged: loadModels()
    Component.onCompleted: loadModels()
    Connections {
        target: settingsController
        function onRouteChanged() { picker.loadModels() }
        function onProviderStateChanged() { picker.loadModels() }
    }
    onActivated: function(value) { settingsController.setRouteModelId(value) }
    onRefreshRequested: settingsController.refreshRouteModels()
    onSecondaryRequested: {
        if (settingsController.routeModelStatus === "not_configured" || settingsController.routeModelStatus === "error")
            connectProvider()
        else modelIdRequested()
    }
}
