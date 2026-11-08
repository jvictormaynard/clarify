import QtQuick 6.5
import QtQuick.Controls 6.5
import QtQuick.Layouts 6.5

SettingsGroup {
    id: root
    required property var controller
    property var access: controller.computerState
    property bool panelOpen: false
    property bool pairAfterStart: false
    property double now: Date.now() / 1000
    title: qsTr("Acesso pelo celular")
    description: access.blocked
        ? qsTr("Saia da conta Clarify para conectar o celular aos seus modelos e serviços pessoais.")
        : qsTr("Use seus modelos e serviços deste computador no iPhone. Mantenha o computador ligado e conectado à rede.")

    function closePairing() {
        panelOpen = false
        pairAfterStart = false
        controller.closeComputerPairing()
    }
    onVisibleChanged: if (!visible) closePairing()
    Connections {
        target: root.controller
        function onComputerStateChanged() {
            if (root.access.blocked && (root.panelOpen || root.pairAfterStart)) root.closePairing()
            if (root.panelOpen && root.pairAfterStart && root.access.running && !root.access.busy) {
                root.pairAfterStart = false
                root.controller.computerCommand("pair", "")
            }
        }
    }
    AppButton {
        objectName: "computerConnectButton"
        theme: root.visualTheme
        text: qsTr("Conectar celular")
        enabled: !root.access.blocked && !root.access.busy && root.access.error !== "unavailable"
        Accessible.name: text
        onClicked: {
            root.panelOpen = true
            if (root.access.running) root.controller.computerCommand("pair", "")
        }
    }
    Label {
        visible: root.access.enabled
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
        color: root.visualTheme.secondaryText
        text: root.access.running ? qsTr("Acesso ativo neste computador.")
            : qsTr("O computador está offline. Pare o acesso e tente novamente.")
    }
    Label {
        visible: root.access.running
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
        color: root.visualTheme.secondaryText
        text: root.access.relayConfigured
            ? (root.access.relayConnected ? qsTr("Acesso pela internet ativo.")
                : qsTr("A conexão pela internet está indisponível. O acesso na mesma rede continua ativo."))
            : qsTr("Acesso disponível na mesma rede Wi-Fi.")
    }
    SettingsSwitch {
        visible: root.access.enabled
        visualTheme: root.visualTheme
        text: qsTr("Manter acesso ao iniciar o Clarify")
        checked: root.access.durable
        enabled: !root.access.busy
        onToggled: root.controller.computerCommand("durable", checked ? "true" : "false")
    }
    Label {
        visible: root.access.enabled
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
        text: qsTr("Ative apenas se quiser aceitar conexões após reiniciar o aplicativo.")
        color: root.visualTheme.secondaryText
    }
    Timer {
        interval: 1000
        running: root.panelOpen
        repeat: true
        onTriggered: root.now = Date.now() / 1000
    }
    ColumnLayout {
        visible: root.panelOpen
        Layout.fillWidth: true
        spacing: 12
        Label {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            color: root.visualTheme.secondaryText
            text: root.access.enabled
                ? qsTr("No Clarify do iPhone, escolha Meu computador e toque em Ler QR do computador. O código funciona uma vez e expira em 5 minutos.")
                : qsTr("Ao ativar, este computador aceita os celulares que você parear. O áudio e o texto usam seus modelos e serviços pessoais.")
        }
        AppButton {
            visible: !root.access.enabled
            theme: root.visualTheme
            text: qsTr("Ativar acesso e gerar QR")
            enabled: !root.access.busy && !root.access.blocked
            Accessible.name: text
            onClicked: {
                root.pairAfterStart = true
                root.controller.computerCommand("enable", "")
            }
        }
        Rectangle {
            visible: root.panelOpen && root.access.pairingReady
            Layout.preferredWidth: 264
            Layout.preferredHeight: 264
            color: "white"
            radius: 8
            Image {
                anchors.fill: parent
                anchors.margins: 12
                cache: false
                source: root.panelOpen && root.access.pairingReady ? root.controller.computerPairingImage : ""
                Accessible.role: Accessible.Graphic
                Accessible.name: qsTr("QR para parear o iPhone")
            }
        }
        Label {
            visible: root.access.pairingReady
            text: qsTr("Expira em {seconds} s").replace("{seconds}", Math.max(0, Math.ceil(root.access.pairingExpiresAt - root.now)))
            color: root.visualTheme.secondaryText
        }
        Label {
            visible: root.access.busy
            text: qsTr("Carregando…")
            color: root.visualTheme.secondaryText
        }
        Label {
            visible: root.access.enabled && !root.access.pairingReady && !root.access.busy
            text: qsTr("Gere um novo QR para conectar o celular.")
            color: root.visualTheme.secondaryText
        }
        RowLayout {
            AppButton {
                visible: root.access.enabled
                theme: root.visualTheme
                text: qsTr("Gerar outro QR")
                enabled: root.access.running && !root.access.busy
                Accessible.name: text
                onClicked: root.controller.computerCommand("pair", "")
            }
            AppButton {
                theme: root.visualTheme
                text: qsTr("Fechar")
                Accessible.name: text
                onClicked: root.closePairing()
            }
        }
    }
    Label {
        visible: root.access.enabled
        text: qsTr("Celulares pareados")
        color: root.visualTheme.secondaryText
    }
    Repeater {
        model: root.access.enabled ? root.access.devices : []
        delegate: RowLayout {
            required property var modelData
            Layout.fillWidth: true
            Label {
                objectName: "computerDeviceName"
                text: modelData.name || qsTr("Celular")
                textFormat: Text.PlainText
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                color: root.visualTheme.secondaryText
            }
            AppButton {
                theme: root.visualTheme
                text: qsTr("Revogar")
                enabled: !root.access.busy
                Accessible.name: qsTr("Revogar acesso de {name}").replace("{name}", modelData.name)
                onClicked: root.controller.computerCommand("revoke", modelData.id)
            }
        }
    }
    Label {
        visible: root.access.enabled && root.access.devices.length === 0
        text: qsTr("Nenhum celular pareado.")
        color: root.visualTheme.secondaryText
    }
    AppButton {
        visible: root.access.enabled
        theme: root.visualTheme
        text: qsTr("Parar acesso")
        enabled: !root.access.busy
        Accessible.name: text
        onClicked: {
            root.closePairing()
            root.controller.computerCommand("stop", "")
        }
    }
    Label {
        visible: root.access.error !== ""
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
        text: root.access.error === "unavailable"
            ? qsTr("O acesso pelo celular não está disponível nesta versão.")
            : root.access.error === "qr_unavailable"
                ? qsTr("Não foi possível gerar o QR. Atualize o Clarify e tente novamente.")
                : qsTr("Não foi possível alterar o acesso do celular. Verifique a conexão e tente novamente.")
        color: root.visualTheme.secondaryText
    }
}
