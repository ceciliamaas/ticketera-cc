document.addEventListener('DOMContentLoaded', function () {
    const isRecurringCheckbox = document.querySelector('#id_is_recurring');
    if (!isRecurringCheckbox) return;

    // Find the occurrence_date column header and all cells in the inline
    function getOccurrenceCols() {
        const headers = document.querySelectorAll('.field-occurrence_date');
        // Also get the th header by looking for the column label
        const ths = document.querySelectorAll('th.column-occurrence_date');
        return [...headers, ...ths];
    }

    function toggleOccurrenceDate(visible) {
        getOccurrenceCols().forEach(el => {
            el.style.display = visible ? '' : 'none';
        });
    }

    // Set initial state
    toggleOccurrenceDate(isRecurringCheckbox.checked);

    // Toggle on change
    isRecurringCheckbox.addEventListener('change', function () {
        toggleOccurrenceDate(this.checked);
    });

    // Also handle dynamically added inline rows
    const observer = new MutationObserver(function () {
        toggleOccurrenceDate(isRecurringCheckbox.checked);
    });
    const inlineGroup = document.querySelector('.inline-group');
    if (inlineGroup) {
        observer.observe(inlineGroup, { childList: true, subtree: true });
    }
});
