import QtQuick 2.12
import Lomiri.Components 1.3
import "../components"

Page {
    id: sp
    property var s: ({})
    property var sys: ({})

    function loadSystem() { py.call("backend.system_status", [], function(r) { sp.sys = r }) }
    function set(key, value) { py.call("backend.set_setting", [key, value], function(r) { sp.s = r }) }
    Component.onCompleted: {
        py.call("backend.get_settings", [], function(r) { sp.s = r })
        loadSystem()
    }
    Connections { target: root; function onDataRevisionChanged() { sp.loadSystem() } }

    header: PageHeader { id: sh; title: i18n.tr("Settings") }

    Flickable {
        anchors { top: sh.bottom; left: parent.left; right: parent.right; bottom: parent.bottom }
        contentHeight: col.height
        clip: true

        Column {
            id: col
            width: parent.width

            SectionHeader { text: i18n.tr("Installing") }
            SwitchRow {
                checked: !!sp.s.pin_after_install
                onToggled: sp.set("pin_after_install", value)
                titleText: i18n.tr("Add installed apps to the launcher")
                subtitleText: i18n.tr("Pin new apps to the Lomiri sidebar right after installing them")
            }
            SwitchRow {
                checked: !!sp.s.connect_gpu
                onToggled: sp.set("connect_gpu", value)
                titleText: i18n.tr("Connect the GPU automatically")
                subtitleText: i18n.tr("Snaps that support it get hardware acceleration through hybris-2404")
            }
            SwitchRow {
                checked: !!sp.s.devmode
                onToggled: sp.set("devmode", value)
                titleText: i18n.tr("Install in devmode")
                subtitleText: i18n.tr("Needed on kernels without the BPF device cgroup (such as 4.14). Turn off only if strict snaps start on your device")
            }
            SwitchRow {
                checked: !!sp.s.known_fixes
                onToggled: sp.set("known_fixes", value)
                titleText: i18n.tr("Apply known fixes")
                subtitleText: i18n.tr("Snaps known to need it (Telegram, PdfCraft…) get the X11 + GPU launch mode right after installing")
            }
            SwitchRow {
                checked: !!sp.s.hide_unsupported
                onToggled: sp.set("hide_unsupported", value)
                titleText: i18n.tr("Hide unsupported snaps")
                subtitleText: i18n.tr("Do not show classic snaps in the results")
            }

            SectionHeader { text: i18n.tr("System checks") }
            StatusRow {
                good: !!sp.sys.hybris
                titleText: i18n.tr("GPU support for snaps (hybris-2404)")
                subtitleText: sp.sys.hybris ? i18n.tr("Installed") : i18n.tr("Not installed: snaps can only use software rendering")
                actionText: i18n.tr("Install")
                onAction: root.run("install", "hybris-2404", ["", false])
            }
            StatusRow {
                good: !!sp.sys.reexec_ok
                titleText: i18n.tr("Snaps see the Android GPU drivers")
                subtitleText: sp.sys.reexec_ok
                               ? i18n.tr("SNAP_REEXEC=0 is set: snaps start with the Ubuntu Touch snapd tools")
                               : i18n.tr("GPU snaps may fail with 'libEGL.so not found'. The fix makes snaps use the Ubuntu Touch snapd tools (takes full effect after logging in again)")
                actionText: i18n.tr("Fix")
                onAction: py.call("backend.fix_reexec", [], function() { sp.loadSystem(); root.toast(i18n.tr("Done")) })
            }
            StatusRow {
                good: !!sp.sys.compat
                titleText: i18n.tr("Compatibility mode (X11 + Turnip)")
                subtitleText: sp.sys.compat ? i18n.tr("Available") : (sp.sys.compat_reason || "")
            }
            StatusRow {
                good: true
                iconName: "reload"
                alwaysAction: true
                titleText: i18n.tr("Reset all snap environments")
                subtitleText: i18n.tr("Fixes snaps that stopped seeing the GPU after an update or a connection change. Running snaps are not stopped")
                actionText: i18n.tr("Reset")
                onAction: root.run("reset-all", "all", [])
            }
            StatusRow {
                good: true
                titleText: "snapd " + (sp.sys.snapd || "")
                subtitleText: sp.sys.snapd_snap ? i18n.tr("The snapd snap is installed as well") : ""
            }

            SectionHeader { text: i18n.tr("Privacy") }
            ListItem {
                height: pwl.height + (divider.visible ? divider.height : 0)
                ListItemLayout {
                    id: pwl
                    title.text: i18n.tr("Forget the password")
                    subtitle.text: i18n.tr("The password is kept only in memory and never written to disk")
                    subtitle.wrapMode: Text.WordWrap
                    Button {
                        SlotsLayout.position: SlotsLayout.Trailing
                        text: i18n.tr("Forget")
                        onClicked: py.call("backend.forget_password", [], function() { root.toast(i18n.tr("Done")) })
                    }
                }
            }
            ListItem {
                height: cl.height + (divider.visible ? divider.height : 0)
                ListItemLayout {
                    id: cl
                    title.text: i18n.tr("Clear the Store cache")
                    subtitle.text: i18n.tr("Store answers are cached for 5 minutes")
                    Button {
                        SlotsLayout.position: SlotsLayout.Trailing
                        text: i18n.tr("Clear")
                        onClicked: py.call("backend.clear_cache", [], function() { root.toast(i18n.tr("Done")) })
                    }
                }
            }

            SectionHeader { text: i18n.tr("About") }
            ListItem {
                height: ab.height
                ListItemLayout {
                    id: ab
                    title.text: "Snapshelf 0.3.1"
                    subtitle.text: i18n.tr("Find and install arm64 snaps that work on Ubuntu Touch. Not affiliated with Canonical. " +
                                           "This project was created in cooperation with an AI assistant.")
                    subtitle.wrapMode: Text.WordWrap
                    subtitle.maximumLineCount: 5
                }
            }
        }
    }
}
