// JavaScript, um die Datei zu laden
fetch('assets/menu.html') // Pfad zur einzubindenden HTML-Datei
.then(response => response.text())
.then(data => {
    document.getElementById('menu').innerHTML = data;
})
.catch(error => {
    console.error('Fehler beim Laden der HTML-Datei:', error);
});

fetch('assets/header.html') // Pfad zur einzubindenden HTML-Datei
.then(response => response.text())
.then(data => {
    document.getElementById('header').innerHTML = data;
})
.catch(error => {
    console.error('Fehler beim Laden der HTML-Datei:', error);
});