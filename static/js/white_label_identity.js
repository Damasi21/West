(() => {
    const root = document.querySelector("[data-identity-editor]");
    if (!root) return;
    const frame = root.querySelector("[data-login-preview]");
    const viewport = root.querySelector("[data-frame-viewport]");
    const form = root.querySelector("form");
    const brandName = root.querySelector("[data-preview-brand-name]").textContent;
    const originals = {}, uploads = {};
    for (const name of ["logo_login", "logo_navbar"]) originals[name] = root.querySelector(`[data-logo-current="${name}"]`).getAttribute("src") || "";
    const value = name => form.elements[name]?.value || "";
    const color = name => /^#[0-9a-f]{6}$/i.test(value(name)) ? value(name) : "#217ed4";
    const light = hex => "#" + [1,3,5].map(i => Math.round(parseInt(hex.slice(i,i+2),16)*.06+255*.94).toString(16).padStart(2,"0")).join("");
    const contrast = hex => {
        const [r,g,b] = [1,3,5].map(i => parseInt(hex.slice(i,i+2),16)/255).map(v => v <= .04045 ? v/12.92 : ((v+.055)/1.055)**2.4);
        const l = r*.2126+g*.7152+b*.0722;
        return 1.05/(l+.05) >= (l+.05)/.05 ? "#ffffff" : "#111827";
    };
    const logo = name => form.elements[`${name}-clear`]?.checked ? "" : (uploads[name] || originals[name]);
    function update() {
        const layout = value("layout_login") === "aurora" ? "aurora" : "classico";
        const p = color("cor_primaria"), s = color("cor_secundaria"), a = color("cor_destaque");
        const bg = layout === "aurora" ? color("cor_fundo") : light(p);
        root.querySelector('[data-color-field="cor_fundo"]').hidden = layout !== "aurora";
        root.querySelector("[data-palette-description]").textContent = layout === "aurora" ? "Quatro cores: principal, secundária, destaque e fundo." : "Três cores: principal, secundária e destaque.";
        root.querySelector("[data-preview-layout]").textContent = layout === "aurora" ? "Aurora · 4 cores" : "Clássico · 3 cores";
        for (const node of root.querySelectorAll("[data-color-field]")) node.querySelector("output").textContent = color(node.dataset.colorField).toUpperCase();
        const nav = root.querySelector("[data-navbar-preview]");
        nav.style.background = p;
        nav.style.borderBottom = `3px solid ${a}`;
        nav.style.color = contrast(p);
        const navLogo = root.querySelector("[data-navbar-logo]");
        navLogo.hidden = !logo("logo_navbar");
        if (!navLogo.hidden) navLogo.src = logo("logo_navbar");
        root.querySelector("[data-preview-brand-name]").hidden = !navLogo.hidden;
        try {
            const doc = frame.contentDocument;
            if (!doc?.body) return;
            const vars = {"--wl-link":contrast(p)==="#ffffff" ? p : contrast(s)==="#ffffff" ? s : "#17243a","--wl-primary":p,"--wl-secondary":s,"--wl-accent":a,"--wl-bg":bg,"--wl-light":light(p),"--wl-on-primary":contrast(p),"--wl-on-secondary":contrast(s),"--wl-on-bg":contrast(bg)};
            for (const [key,val] of Object.entries(vars)) doc.documentElement.style.setProperty(key,val);
            doc.body.classList.remove("wl-layout-classico","wl-layout-aurora");
            doc.body.classList.add(`wl-layout-${layout}`);
            const content = doc.querySelector(".visual-content");
            if (content) {
                let image = content.querySelector(".visual-logo");
                let text = content.querySelector(".visual-brand-name");
                if (logo("logo_login")) {
                    if (!image) { image = doc.createElement("img"); image.className = "visual-logo"; image.alt = brandName; content.prepend(image); }
                    image.src = logo("logo_login"); image.hidden = false; if (text) text.hidden = true;
                } else {
                    if (image) image.hidden = true;
                    if (!text) { text = doc.createElement("strong"); text.className = "visual-brand-name"; text.textContent = brandName; content.prepend(text); }
                    text.hidden = false;
                }
            }
        } catch (_) { /* A previa nunca impede o salvamento do formulario. */ }
    }
    function resize() {
        const scale = viewport.clientWidth/1200;
        frame.style.transform = `scale(${scale})`;
        viewport.style.height = `${780*scale}px`;
    }
    for (const name of ["logo_login","logo_navbar"]) {
        form.elements[name].addEventListener("change", () => {
            if (uploads[name]) { URL.revokeObjectURL(uploads[name]); delete uploads[name]; }
            const file = form.elements[name].files[0];
            const feedback = root.querySelector("[data-upload-feedback]");
            feedback.textContent = "";
            if (file && (!['image/png','image/jpeg','image/webp'].includes(file.type) || file.size>3*1024*1024)) feedback.textContent = "Use PNG, JPG ou WebP de até 3 MB. A imagem será validada ao salvar.";
            else if (file) { uploads[name] = URL.createObjectURL(file); if (form.elements[`${name}-clear`]) form.elements[`${name}-clear`].checked = false; }
            const current = root.querySelector(`[data-logo-current="${name}"]`);
            current.hidden = !logo(name); if (!current.hidden) current.src = logo(name);
            update();
        });
    }
    form.addEventListener("input", update);
    form.addEventListener("change", update);
    frame.addEventListener("load", () => { update(); resize(); });
    new ResizeObserver(resize).observe(viewport);
    window.addEventListener("beforeunload", () => Object.values(uploads).forEach(URL.revokeObjectURL));
    update(); resize();
})();
