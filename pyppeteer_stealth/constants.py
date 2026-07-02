CHROME_PATHS: list[str] = [
    "/usr/bin/google-chrome",
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
]

STEALTH_FLAGS: list[str] = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-infobars",
]

STEALTH_SCRIPT: str = """
delete Object.getPrototypeOf(navigator).webdriver;

window.chrome = {
    runtime: {},
    loadTimes: function() {},
    csi: function() {},
    app: {}
};

const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : originalQuery(parameters)
);

(() => {
    const makePlugin = (name, filename, description) => {
        const plugin = Object.create(Plugin.prototype);
        Object.defineProperties(plugin, {
            name: { value: name, enumerable: true },
            filename: { value: filename, enumerable: true },
            description: { value: description, enumerable: true },
            length: { value: 1, enumerable: true }
        });
        return plugin;
    };

    const pluginData = [
        ['Chrome PDF Plugin', 'internal-pdf-viewer', 'Portable Document Format'],
        ['Chrome PDF Viewer', 'mhjfbmdgcfjbbpaeojofohoefgiehjai', ''],
        ['Native Client', 'internal-nacl-plugin', ''],
        ['WebKit built-in PDF', 'webkit-pdf', 'Portable Document Format'],
        ['Widevine Content Decryption Module', 'widevinecdm', 'Enables Widevine licenses']
    ];

    const pluginArray = Object.create(PluginArray.prototype);
    pluginData.forEach((data, index) => {
        const plugin = makePlugin(data[0], data[1], data[2]);
        Object.defineProperty(pluginArray, index, { value: plugin, enumerable: true });
        Object.defineProperty(pluginArray, plugin.name, { value: plugin });
    });
    Object.defineProperty(pluginArray, 'length', { value: pluginData.length });
    Object.defineProperty(pluginArray, 'item', {
        value: function(i) { return this[i]; }
    });
    Object.defineProperty(pluginArray, 'namedItem', {
        value: function(name) { return this[name]; }
    });

    Object.defineProperty(navigator, 'plugins', {
        get: () => pluginArray
    });
})();

Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en']
});

const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(parameter) {
    if (parameter === 37445) return 'Intel Inc.';
    if (parameter === 37446) return 'Intel Iris OpenGL Engine';
    return getParameter.call(this, parameter);
};
"""
