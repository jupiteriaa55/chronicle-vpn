package com.jupiteriaa55.chroniclevpn;

import android.content.Intent;
import android.net.Uri;
import androidx.core.content.FileProvider;

import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;

/**
 * Bridge: writes the .conf to app-private cache, then sends an ACTION_VIEW
 * intent for application/x-wireguard-profile so the official WireGuard app
 * (com.wireguard.android) imports it as a tunnel.
 */
@CapacitorPlugin(name = "WireGuardImporter")
public class WireGuardImporterPlugin extends Plugin {

    @PluginMethod
    public void importConfig(PluginCall call) {
        String text = call.getString("text");
        if (text == null || text.isEmpty()) {
            call.reject("missing 'text'");
            return;
        }

        try {
            File dir = new File(getContext().getCacheDir(), "wg-import");
            if (!dir.exists() && !dir.mkdirs()) {
                call.reject("failed to create cache dir");
                return;
            }
            File out = new File(dir, "chronicle-vpn.conf");
            try (FileOutputStream fos = new FileOutputStream(out)) {
                fos.write(text.getBytes(StandardCharsets.UTF_8));
            }

            String authority = getContext().getPackageName() + ".fileprovider";
            Uri uri = FileProvider.getUriForFile(getContext(), authority, out);

            Intent intent = new Intent(Intent.ACTION_VIEW);
            intent.setDataAndType(uri, "application/x-wireguard-profile");
            intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            // Try the official WireGuard app explicitly first; fall back to chooser.
            Intent explicit = new Intent(intent);
            explicit.setPackage("com.wireguard.android");
            try {
                getContext().startActivity(explicit);
            } catch (android.content.ActivityNotFoundException ex) {
                getContext().startActivity(Intent.createChooser(intent, "Import VPN tunnel"));
            }
            call.resolve();
        } catch (Exception e) {
            call.reject("import failed: " + e.getMessage(), e);
        }
    }
}
