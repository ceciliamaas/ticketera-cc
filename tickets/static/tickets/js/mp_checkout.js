document.addEventListener('DOMContentLoaded', function () {
    var container = document.querySelector('.cho-container');
    if (!container) return;

    var publicKey = container.dataset.mpPublicKey;
    var preferenceId = container.dataset.mpPreferenceId;
    if (!publicKey || !preferenceId) return;

    var mp = new MercadoPago(publicKey, { locale: 'es-AR' });
    mp.checkout({
        preference: { id: preferenceId },
        render: {
            container: '.cho-container',
            label: 'Pagar',
        }
    });
});
