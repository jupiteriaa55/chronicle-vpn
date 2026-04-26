package com.jupiteriaa55.chroniclevpn;

import android.os.Bundle;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(WireGuardImporterPlugin.class);
        super.onCreate(savedInstanceState);
    }
}
