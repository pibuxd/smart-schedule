package pl.grafikomat.app;

import android.app.Activity;
import android.content.BroadcastReceiver;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.os.Build;
import android.os.Bundle;
import androidx.activity.result.ActivityResult;
import androidx.core.content.ContextCompat;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.ActivityCallback;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.google.android.gms.auth.api.phone.SmsRetriever;
import com.google.android.gms.common.api.CommonStatusCodes;
import com.google.android.gms.common.api.Status;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Small native helpers of the Android app (src/native/native-plugin.ts).
 *
 * - info(): whether push can be switched on (the build has google-services.json; without it Firebase is not set up
 *   and registering for push would stop the app).
 * - waitForSmsCode(): the SMS User Consent API. Android shows the next SMS with a code (from a sender who is not in
 *   the contacts, within 5 minutes) and asks whether Grafikomat may read that one message. The app never gets
 *   the permission to read SMS messages, only this one message after the person taps "Zezwól".
 */
@CapacitorPlugin(name = "Grafikomat")
public class GrafikomatPlugin extends Plugin {

    private static final Pattern CODE = Pattern.compile("(?<!\\d)(\\d{6})(?!\\d)");
    private static final String PLAY_SERVICES = "com.google.android.gms";

    private PluginCall waiting;
    private boolean receiverRegistered = false;

    private final BroadcastReceiver smsReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            if (!SmsRetriever.SMS_RETRIEVED_ACTION.equals(intent.getAction()) || waiting == null) {
                return;
            }
            Bundle extras = intent.getExtras();
            Status status = extras == null ? null : readParcelable(extras, SmsRetriever.EXTRA_STATUS, Status.class);
            if (status == null || status.getStatusCode() != CommonStatusCodes.SUCCESS) {
                finish(null, "Nie przyszedł SMS z kodem.");
                return;
            }
            Intent consent = readParcelable(extras, SmsRetriever.EXTRA_CONSENT_INTENT, Intent.class);
            // Only Google Play services' own consent screen, never another app's activity (intent redirection).
            ComponentName target = consent == null ? null : consent.resolveActivity(getContext().getPackageManager());
            if (target == null || !PLAY_SERVICES.equals(target.getPackageName())) {
                finish(null, "Nie można odczytać SMS-a.");
                return;
            }
            consent.setFlags(consent.getFlags() & ~(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION));
            startActivityForResult(waiting, consent, "consentResult");
        }
    };

    @PluginMethod
    public void info(PluginCall call) {
        JSObject result = new JSObject();
        result.put("push", getContext().getResources().getBoolean(R.bool.grafikomat_push));
        call.resolve(result);
    }

    @PluginMethod(returnType = PluginMethod.RETURN_PROMISE)
    public void waitForSmsCode(PluginCall call) {
        finish(null, "Czekamy na nowy SMS.");
        waiting = call;
        call.setKeepAlive(true);
        registerReceiver();
        SmsRetriever.getClient(getContext())
            .startSmsUserConsent(null)
            .addOnFailureListener((error) -> finish(null, "Nie można czekać na SMS."));
    }

    @PluginMethod
    public void stopSmsCode(PluginCall call) {
        finish(null, "Wpisano kod.");
        call.resolve();
    }

    @ActivityCallback
    private void consentResult(PluginCall call, ActivityResult result) {
        Intent data = result.getData();
        if (result.getResultCode() != Activity.RESULT_OK || data == null) {
            finish(null, "Bez zgody na odczyt SMS-a.");
            return;
        }
        Matcher matcher = CODE.matcher(String.valueOf(data.getStringExtra(SmsRetriever.EXTRA_SMS_MESSAGE)));
        finish(matcher.find() ? matcher.group(1) : null, "W SMS-ie nie ma kodu.");
    }

    @Override
    protected void handleOnDestroy() {
        finish(null, "Aplikacja zamknięta.");
        super.handleOnDestroy();
    }

    /** Resolve the waiting call with the code, or reject it with the reason; stop listening either way. */
    private void finish(String code, String reason) {
        unregisterReceiver();
        PluginCall call = waiting;
        waiting = null;
        if (call == null) {
            return;
        }
        call.setKeepAlive(false);
        if (code != null) {
            JSObject result = new JSObject();
            result.put("code", code);
            call.resolve(result);
        } else {
            call.reject(reason);
        }
        bridge.releaseCall(call);
    }

    private void registerReceiver() {
        if (receiverRegistered) {
            return;
        }
        IntentFilter filter = new IntentFilter(SmsRetriever.SMS_RETRIEVED_ACTION);
        // Only Google Play services can send this broadcast (it holds SEND_PERMISSION).
        ContextCompat.registerReceiver(
            getContext(),
            smsReceiver,
            filter,
            SmsRetriever.SEND_PERMISSION,
            null,
            ContextCompat.RECEIVER_EXPORTED
        );
        receiverRegistered = true;
    }

    private void unregisterReceiver() {
        if (!receiverRegistered) {
            return;
        }
        try {
            getContext().unregisterReceiver(smsReceiver);
        } catch (IllegalArgumentException ignored) {
            // Already gone.
        }
        receiverRegistered = false;
    }

    @SuppressWarnings("deprecation")
    private static <T extends android.os.Parcelable> T readParcelable(Bundle extras, String key, Class<T> type) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            return extras.getParcelable(key, type);
        }
        Object value = extras.get(key);
        return type.isInstance(value) ? type.cast(value) : null;
    }
}
