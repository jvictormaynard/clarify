import QtQuick 6.5
import QtQuick.Controls 6.5

ItemDelegate {
    id: delegate
    required property Theme theme
    required property var comboBox
    property var displayTextForIndex: null

    width: comboBox && comboBox.popup
           ? Math.max(0, comboBox.popup.width
                      - comboBox.popup.leftPadding
                      - comboBox.popup.rightPadding)
           : 0
    height: 30
    padding: 0
    leftPadding: 10
    rightPadding: 10
    hoverEnabled: true
    highlighted: comboBox && comboBox.highlightedIndex === index

    contentItem: Label {
        text: comboBox && index >= 0
              ? (delegate.displayTextForIndex
                 ? delegate.displayTextForIndex(index, comboBox.textAt(index))
                 : comboBox.textAt(index))
              : ""
        color: delegate.highlighted || delegate.hovered
               ? delegate.theme.text : delegate.theme.secondaryText
        font.pixelSize: 11
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    background: Rectangle {
        radius: 7
        color: delegate.down
               ? delegate.theme.controlPressed
               : delegate.highlighted || delegate.hovered
                 ? delegate.theme.controlHover : "transparent"
    }
}
