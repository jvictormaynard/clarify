import QtQuick 6.5
import QtQuick.Controls 6.5

ItemDelegate {
    id: delegate
    required property Theme visualTheme
    required property var comboBox
    required property int index
    required property var model
    property var displayTextForIndex: null

    width: ListView.view ? ListView.view.width : (comboBox ? comboBox.width : 0)
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
               ? delegate.visualTheme.text : delegate.visualTheme.secondaryText
        font.pixelSize: 11
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    background: Rectangle {
        radius: 7
        color: delegate.down
               ? delegate.visualTheme.controlPressed
               : delegate.highlighted || delegate.hovered
                 ? delegate.visualTheme.controlHover : "transparent"
    }
}
