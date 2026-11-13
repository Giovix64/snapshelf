import QtQuick 2.12
import Lomiri.Components 1.3
import "../components"

Page {
    id: page
    property int section: 0               // 0 discover, 1 installed, 2 updates
    property var items: []
    property bool loading: false
    property string error: ""
    property var categories: []
    property string category: ""          // "" = featured
    property int requestId: 0             // drop stale answers

    function reload() {
        if (!root.ready) return
        var id = ++requestId
        loading = true; error = ""
        if (section === 0) {
            py.call("backend.search", [searchField.text, category], function(res) {
                if (id !== page.requestId) return
                loading = false; error = res.error; items = res.items
            })
        } else {
            py.call("backend.installed", [], function(res) {
                if (id !== page.requestId) return
                loading = false
                items = section === 2 ? res.filter(function(s) { return s.update }) : res
            })
        }
    }
    function openSnap(s) {
        root.openDetail(s.name, s.title)
    }

    Connections {
        target: root
        function onReadyChanged() {
            page.reload()
            py.call("backend.categories", [], function(c) { page.categories = c })
        }
        function onDataRevisionChanged() { if (page.section !== 0) page.reload() }
    }
    Component.onCompleted: if (root.ready) { reload(); py.call("backend.categories", [], function(c) { page.categories = c }) }

    header: PageHeader {
        id: header
        title: "Snapshelf"
        subtitle: i18n.tr("arm64 snaps for Ubuntu Touch")
        trailingActionBar.actions: [
            Action { iconName: "settings"; text: i18n.tr("Settings"); onTriggered: root.openSettings() },
            Action { iconName: "reload"; text: i18n.tr("Reload"); onTriggered: { py.call("backend.clear_cache", []); page.reload(); root.reloadUpdates() } }
        ]
        extension: Sections {
            anchors { left: parent.left; bottom: parent.bottom; leftMargin: units.gu(1) }
            model: [i18n.tr("Discover"), i18n.tr("Installed"),
                    root.updates > 0 ? i18n.tr("Updates (%1)").arg(root.updates) : i18n.tr("Updates")]
            onSelectedIndexChanged: { page.section = selectedIndex; page.items = []; page.reload() }
        }
    }

    // ---------------------------------------------------------------- search + categories
    Column {
        id: top
        anchors { top: header.bottom; left: parent.left; right: parent.right; topMargin: units.gu(1) }
        spacing: units.gu(1)
        visible: page.section === 0
        height: visible ? implicitHeight : 0

        TextField {
            id: searchField
            anchors { left: parent.left; right: parent.right; margins: units.gu(1.5) }
            placeholderText: i18n.tr("Search snaps")
            primaryItem: Icon { height: units.gu(2); width: height; name: "find" }
            inputMethodHints: Qt.ImhNoPredictiveText
            onTextChanged: debounce.restart()
            onAccepted: { debounce.stop(); page.reload() }
            Timer { id: debounce; interval: 450; onTriggered: page.reload() }
        }
        ListView {
            id: cats
            anchors { left: parent.left; right: parent.right }
            height: units.gu(4.5)
            orientation: ListView.Horizontal
            spacing: units.gu(1)
            leftMargin: units.gu(1.5); rightMargin: units.gu(1.5)
            clip: true
            model: [{ "name": "", "title": i18n.tr("Featured") }].concat(page.categories)
            delegate: Button {
                height: units.gu(4)
                width: implicitWidth + units.gu(2)
                text: modelData.title
                strokeColor: page.category === modelData.name ? theme.palette.normal.focus : theme.palette.normal.base
                color: page.category === modelData.name ? theme.palette.normal.focus : "transparent"
                onClicked: { page.category = modelData.name; page.reload() }
            }
        }
    }

    // ---------------------------------------------------------------- updates toolbar
    Button {
        id: updateAll
        visible: page.section === 2 && page.items.length > 0
        height: visible ? units.gu(5) : 0
        anchors { top: top.bottom; left: parent.left; right: parent.right; margins: units.gu(1.5) }
        text: i18n.tr("Update all")
        color: theme.palette.normal.positive
        onClicked: root.refreshAll()
    }

    ListView {
        id: list
        anchors { top: updateAll.bottom; topMargin: units.gu(1); left: parent.left; right: parent.right; bottom: parent.bottom }
        clip: true
        cacheBuffer: units.gu(60)
        model: page.items
        delegate: SnapDelegate {
            snap: modelData
            showBadge: page.section !== 1 || modelData.level === "update" || modelData.level === "devmode"
            onOpen: page.openSnap(modelData)
        }
        PullToRefresh {
            refreshing: page.loading
            onRefresh: { py.call("backend.clear_cache", []); page.reload(); root.reloadUpdates() }
        }
    }

    ActivityIndicator { anchors.centerIn: list; running: page.loading && page.items.length === 0; visible: running }
    Column {
        anchors.centerIn: list
        width: list.width - units.gu(6)
        spacing: units.gu(2)
        visible: !page.loading && (page.error !== "" || page.items.length === 0)
        Icon {
            anchors.horizontalCenter: parent.horizontalCenter
            width: units.gu(8); height: width
            name: page.error !== "" ? "network-offline-symbolic" : (page.section === 2 ? "tick" : "search")
            color: theme.palette.normal.backgroundTertiaryText
        }
        Label {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: page.error !== "" ? page.error
                  : page.section === 0 ? i18n.tr("No results")
                  : page.section === 1 ? i18n.tr("No snap applications installed")
                  : i18n.tr("Everything is up to date")
        }
    }
}
