export function toast(message, type = "success") {
    const element = document.createElement("div");
    element.className = `toast ${type}`;
    element.textContent = message;
    document.body.appendChild(element);
    setTimeout(() => element.remove(), 3000);
}
