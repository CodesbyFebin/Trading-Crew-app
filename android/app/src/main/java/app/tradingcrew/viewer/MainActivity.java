package app.tradingcrew.viewer;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.SharedPreferences;
import android.os.Bundle;
import android.text.InputType;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.EditText;
import android.widget.LinearLayout;
import org.json.JSONObject;

/** Thin read-only client: shows the UI served by the user's OWN desktop/server instance. No trading engine runs on the phone.
 *  The viewer token is stored in app-private storage (backups disabled) and handed to the page via sessionStorage, never in the URL. */
public class MainActivity extends Activity {
    private WebView web; private SharedPreferences prefs;

    @Override protected void onCreate(Bundle b) {
        super.onCreate(b);
        prefs = getSharedPreferences("crew", MODE_PRIVATE);
        web = new WebView(this);
        WebSettings s = web.getSettings(); s.setJavaScriptEnabled(true); s.setDomStorageEnabled(true);
        s.setAllowFileAccess(false); s.setAllowContentAccess(false);
        web.setWebViewClient(new WebViewClient() {
            @Override public void onPageFinished(WebView v, String url) {
                String tok = prefs.getString("token", "");
                v.evaluateJavascript("if(typeof TOK!=='undefined'&&!TOK){TOK=" + JSONObject.quote(tok) + ";sessionStorage.tok=TOK;render()}", null);
            }
        });
        setContentView(web);
        if (prefs.getString("url", "").isEmpty()) setup(); else web.loadUrl(prefs.getString("url", ""));
    }

    private void setup() {
        LinearLayout l = new LinearLayout(this); l.setOrientation(LinearLayout.VERTICAL); l.setPadding(40, 20, 40, 0);
        EditText url = new EditText(this); url.setHint("http://192.168.1.10:8790/"); url.setText(prefs.getString("url", ""));
        EditText tok = new EditText(this); tok.setHint("viewer token (trading-crew --print-viewer-token)");
        tok.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        l.addView(url); l.addView(tok);
        new AlertDialog.Builder(this).setTitle("Connect to your Trading Crew")
            .setMessage("Use your own desktop instance started with --lan. Use a VIEWER token only; never an owner token.")
            .setView(l).setCancelable(false)
            .setPositiveButton("Connect", (d, w) -> {
                String u = url.getText().toString().trim(); if (!u.endsWith("/")) u += "/";
                prefs.edit().putString("url", u).putString("token", tok.getText().toString().trim()).apply();
                web.loadUrl(u);
            }).show();
    }

    @Override public void onBackPressed() { if (web.canGoBack()) web.goBack(); else super.onBackPressed(); }
    @Override public boolean onKeyLongPress(int k, android.view.KeyEvent e) {
        if (k == android.view.KeyEvent.KEYCODE_BACK) { prefs.edit().clear().apply(); web.clearCache(true); setup(); return true; }
        return super.onKeyLongPress(k, e);
    }
}
