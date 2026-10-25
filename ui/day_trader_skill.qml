import QtQuick.Layouts 1.4
import QtQuick 2.4
import QtQuick.Controls 2.0
import org.kde.kirigami 2.4 as Kirigami
import Mycroft 1.0 as Mycroft

Mycroft.Delegate {
    id: root
    
    Rectangle {
        anchors.fill: parent
        color: "#0f172a"

        ColumnLayout {
            anchors.centerIn: parent
            spacing: 20

            Text {
                text: "Indian Index Options"
                font.bold: true
                font.pixelSize: 28
                color: "#38bdf8"
                Layout.alignment: Qt.AlignHCenter
            }

            Rectangle {
                Layout.alignment: Qt.AlignHCenter
                width: 380
                height: 180
                radius: 12
                color: "#1e293b"
                border.color: "#334155"
                border.width: 1

                ColumnLayout {
                    anchors.centerIn: parent
                    spacing: 10

                    Text {
                        text: sessionData.index_name || "INDEX"
                        font.pixelSize: 24
                        font.bold: true
                        color: "#f8fafc"
                        Layout.alignment: Qt.AlignHCenter
                    }

                    Text {
                        text: sessionData.spot_price || "₹0.00"
                        font.pixelSize: 36
                        font.bold: true
                        color: "#4ade80"
                        Layout.alignment: Qt.AlignHCenter
                    }

                    Text {
                        visible: sessionData.atm_strike !== undefined && sessionData.atm_strike !== ""
                        text: "Nearest ATM: " + (sessionData.atm_strike || "")
                        font.pixelSize: 18
                        color: "#94a3b8"
                        Layout.alignment: Qt.AlignHCenter
                    }
                }
            }
        }
    }
}
