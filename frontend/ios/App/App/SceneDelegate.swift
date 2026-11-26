import UIKit
import UserNotifications
import Capacitor

class SceneDelegate: UIResponder, UIWindowSceneDelegate {
    var window: UIWindow?

    /// The tap on a push notification that started the app, kept until the plugins are loaded.
    private var launchTap: UNNotificationResponse?
    private var launchTapObserver: NSObjectProtocol?

    func scene(_ scene: UIScene, willConnectTo session: UISceneSession, options connectionOptions: UIScene.ConnectionOptions) {
        guard let windowScene = scene as? UIWindowScene else { return }

        window = UIWindow(windowScene: windowScene)
        window?.rootViewController = CAPBridgeViewController()
        window?.makeKeyAndVisible()

        // A tap that creates the scene comes in `connectionOptions.notificationResponse`. Capacitor's scene proxy
        // passes on URLs and user activities but not this, and its notification router becomes the notification
        // center's delegate only now, after launch, so the plugin may never hear of the tap and the app would open
        // on its start screen. Keep the tap until the web view has appeared (the plugins are loaded by then) and
        // hand it to the router once; the push plugin holds it until the app listens (src/native/push.ts, which
        // also opens a tap that reaches it twice only once).
        if let response = connectionOptions.notificationResponse {
            launchTap = response
            launchTapObserver = NotificationCenter.default.addObserver(
                forName: .capacitorViewDidAppear, object: nil, queue: .main
            ) { [weak self] _ in
                self?.deliverLaunchTap()
            }
        }

        SceneDelegateProxy.shared.scene(scene, willConnectTo: session, options: connectionOptions)
    }

    private func deliverLaunchTap() {
        if let observer = launchTapObserver {
            NotificationCenter.default.removeObserver(observer)
            launchTapObserver = nil
        }
        guard let response = launchTap,
              let bridge = (window?.rootViewController as? CAPBridgeViewController)?.bridge else { return }
        launchTap = nil
        bridge.notificationRouter.userNotificationCenter(
            UNUserNotificationCenter.current(), didReceive: response, withCompletionHandler: {}
        )
    }

    func scene(_ scene: UIScene, openURLContexts URLContexts: Set<UIOpenURLContext>) {
        SceneDelegateProxy.shared.scene(scene, openURLContexts: URLContexts)
    }

    func scene(_ scene: UIScene, continue userActivity: NSUserActivity) {
        SceneDelegateProxy.shared.scene(scene, continue: userActivity)
    }
}
