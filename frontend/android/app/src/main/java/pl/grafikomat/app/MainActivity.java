package pl.grafikomat.app;

import android.os.Bundle;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {

    @Override
    public void onCreate(Bundle savedInstanceState) {
        // The app's own plugin (SMS code, push availability) is registered before the bridge starts.
        registerPlugin(GrafikomatPlugin.class);
        super.onCreate(savedInstanceState);
    }
}
