import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

function createPreview(node) {
    const container = document.createElement("div");
    container.className = "hdr-native-preview";
    container.style.cssText = "width:100%;height:100%;min-height:180px;display:flex;flex-direction:column;gap:6px;background:#161616;color:#ddd;overflow:hidden;";
    const image = document.createElement("img");
    image.alt = "HDR preview";
    image.draggable = false;
    image.style.cssText = "display:none;flex:1;min-height:0;width:100%;object-fit:contain;dynamic-range-limit:no-limit;";
    const status = document.createElement("div");
    status.setAttribute("role", "alert");
    status.style.cssText = "flex:none;padding:4px 6px;font:12px sans-serif;white-space:normal;";
    status.hidden = true;
    const actions = document.createElement("div");
    actions.style.cssText = "display:flex;gap:8px;flex:none;padding:6px;margin-top:auto;";
    function makeButton(label, title) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = label;
        button.title = title;
        button.disabled = true;
        button.style.cssText = "flex:1;padding:6px 10px;border:1px solid #555;border-radius:6px;background:#303030;color:inherit;font:13px sans-serif;cursor:pointer;";
        button.addEventListener("pointerdown", event => event.stopPropagation());
        button.addEventListener("mousedown", event => event.stopPropagation());
        button.addEventListener("keydown", event => event.stopPropagation());
        actions.append(button);
        return button;
    }
    const openButton = makeButton("Открыть", "Открыть оригинальный HDR AVIF в новой вкладке");
    const saveButton = makeButton("Сохранить", "Скачать текущий HDR AVIF");
    container.append(image, status, actions);
    const widget = node.addDOMWidget("hdr_native_preview", "HDR_NATIVE_PREVIEW", container, {
        serialize: false,
        hideOnZoom: false,
        getMinHeight: () => 220,
        getMaxHeight: () => 800,
    });
    widget.serialize = false;
    let current = null;
    let sequence = 0;
    let ready = false;
    let busy = false;
    let controller = null;

    function updateButtons() {
        for (const button of [openButton, saveButton]) {
            button.disabled = !ready || busy;
            button.style.opacity = button.disabled ? "0.45" : "1";
        }
    }

    function showError(message) {
        status.textContent = message;
        status.hidden = false;
    }

    function originalUrl(data) {
        const query = new URLSearchParams({ filename: data.filename, subfolder: data.subfolder, type: "temp" });
        return api.apiURL(`/view?${query}`);
    }

    async function perform(action) {
        if (!ready || busy || !current) return;
        const generation = sequence;
        const data = current;
        const request = new AbortController();
        controller = request;
        let popup = null;
        busy = true;
        status.hidden = true;
        updateButtons();
        try {
            if (action === "open") {
                popup = window.open("about:blank", "_blank");
                if (!popup) {
                    showError("Браузер заблокировал новую вкладку. Разрешите всплывающие окна для ComfyUI.");
                    return;
                }
                popup.opener = null;
            }
            const url = originalUrl(data);
            const response = await fetch(url, {
                method: action === "open" ? "HEAD" : "GET",
                cache: "no-store",
                signal: request.signal,
            });
            if (!response.ok) {
                if (response.status === 404 && generation === sequence) ready = false;
                throw new Error(response.status === 404
                    ? "Превью истекло. Выполните ноду ещё раз."
                    : "Не удалось получить HDR AVIF. Повторите попытку.");
            }
            if (generation !== sequence) return;
            if (action === "open") {
                popup.location.replace(new URL(url, window.location.href).href);
                popup = null;
            } else {
                const blob = await response.blob();
                if (generation !== sequence) return;
                const blobUrl = URL.createObjectURL(blob);
                const link = document.createElement("a");
                link.href = blobUrl;
                link.download = data.filename;
                document.body.append(link);
                link.click();
                link.remove();
                setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
            }
        } catch (error) {
            if (error.name !== "AbortError" && generation === sequence) {
                showError(error.name === "TypeError" ? "Не удалось связаться с ComfyUI. Повторите попытку." : error.message || "Не удалось открыть или сохранить HDR AVIF.");
            }
        } finally {
            popup?.close();
            if (generation === sequence) {
                controller = null;
                busy = false;
                updateButtons();
            }
        }
    }

    openButton.addEventListener("click", () => perform("open"));
    saveButton.addEventListener("click", () => perform("save"));
    updateButtons();
    const previousRemove = node.onRemoved;
    node.onRemoved = function (...args) {
        sequence++;
        controller?.abort();
        image.removeAttribute("src");
        return previousRemove?.apply(this, args);
    };

    return {
        show(data) {
            if (!data || !/^hdr_preview_[0-9a-f]{32}\.avif$/.test(data.filename) || data.type !== "temp" || data.subfolder !== "hdr-preview") return;
            current = data;
            const generation = ++sequence;
            controller?.abort();
            controller = null;
            ready = false;
            busy = false;
            updateButtons();
            image.style.display = "none";
            status.hidden = true;
            status.textContent = "";
            image.onload = () => {
                if (generation !== sequence) return;
                image.style.display = "block";
                ready = true;
                status.hidden = true;
                updateButtons();
                node.setDirtyCanvas?.(true, true);
            };
            image.onerror = () => {
                if (generation !== sequence) return;
                image.style.display = "none";
                ready = false;
                updateButtons();
                showError("Не удалось загрузить HDR AVIF: превью истекло или браузер не поддерживает AVIF. Выполните ноду ещё раз.");
            };
            image.src = originalUrl(data);
        },
    };
}

app.registerExtension({
    name: "NativeHDR.Preview",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "PreviewHDR") return;
        const previousCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function (...args) {
            const result = previousCreated?.apply(this, args);
            this._nativeHdrPreview = createPreview(this);
            this.setSize([Math.max(this.size[0], 360), Math.max(this.size[1], 360)]);
            return result;
        };
        const previousExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            const result = previousExecuted?.apply(this, arguments);
            this._nativeHdrPreview?.show(message?.hdr_preview?.[0]);
            return result;
        };
    },
});
