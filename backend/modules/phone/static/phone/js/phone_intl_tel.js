'use strict';
// Turn any <input class="intl-tel"> into an intl-tel-input field: a single
// input with a searchable flag/country dropdown and live formatting. On submit
// the raw value is replaced with the full E.164 number so the backend (which
// validates/stores E.164) receives a canonical value.
{
    function initIntlTel(input) {
        if (input.dataset.itiInitialized) {
            return;
        }
        input.dataset.itiInitialized = '1';

        const iti = window.intlTelInput(input, {
            initialCountry: input.dataset.initialCountry || 'br',
            separateDialCode: true,
            strictMode: true,
            // The admin's .form-row uses `overflow: hidden`, which would clip
            // the country dropdown. Rendering it on <body> escapes that clip.
            dropdownContainer: document.body,
            // utils is bundled in intlTelInputWithUtils, so no loadUtils needed.
        });

        const form = input.closest('form');
        if (form) {
            form.addEventListener('submit', function () {
                // Only rewrite when there's a value, so an empty optional field
                // stays empty instead of becoming a bare dial code.
                if (input.value.trim()) {
                    input.value = iti.getNumber();
                }
            });
        }
    }

    function initAll() {
        document.querySelectorAll('input.intl-tel').forEach(initIntlTel);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAll);
    } else {
        initAll();
    }
}
