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
    caption: qsTr("Choose a model")
    placeholderText: qsTr("Choose a model")
    searchPlaceholder: qsTr("Search models…")
    refreshable: settingsController.routeModelStatus !== "not_configured"
    busy: settingsController.routeModelStatus === "loading"
    secondaryActionText: settingsController.routeProviderId === "local_asr" ? ""
                        : settingsController.routeModelStatus === "not_configured"
                        || settingsController.routeModelStatus === "error" ? qsTr("Connect service") : qsTr("Use model ID…")
    statusText: {
        var status = settingsController.routeModelStatus
        if (settingsController.routeProviderId === "local_asr") {
            if (status === "loading") return qsTr("Checking installed models…")
            if (status === "empty") return qsTr("No installed models. Install one in Integrations.")
            if (status === "error") return qsTr("Could not check local models. Try refresh.")
        }
        if (status === "loading") return qsTr("Loading models…")
        if (status === "not_configured") return qsTr("Connect this service to browse its models.")
        if (status === "error") return qsTr("Could not load models. Check the connection and retry.")
        if (status === "empty") return qsTr("No compatible models returned by this service.")
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
