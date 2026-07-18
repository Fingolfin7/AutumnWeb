(function () {
    'use strict';

    const COLORS = ['#7896b8', '#7ca36a', '#b9a66a', '#9b83a7', '#4e9a8e', '#c98245'];
    const LOCK_OPEN = '<i class="fa fa-lock-open" aria-hidden="true"></i>';
    const LOCK_CLOSED = '<i class="fa fa-lock" aria-hidden="true"></i>';

    function clamp(value, low, high) {
        return Math.max(low, Math.min(high, value));
    }

    function distribute(total, weights) {
        const count = weights.length;
        if (!count) return [];
        total = Math.max(0, Math.round(total));
        const weightTotal = weights.reduce((sum, value) => sum + Math.max(0, value), 0);
        const raw = weightTotal
            ? weights.map(value => total * Math.max(0, value) / weightTotal)
            : weights.map(() => total / count);
        const result = raw.map(Math.floor);
        let left = total - result.reduce((sum, value) => sum + value, 0);
        const order = raw.map((value, index) => ({ index, fraction: value - Math.floor(value) }))
            .sort((a, b) => b.fraction - a.fraction || a.index - b.index);
        for (let index = 0; index < left; index += 1) result[order[index].index] += 1;
        return result;
    }

    function evenValues(count) {
        return distribute(100, Array(count).fill(1));
    }

    function distributePositive(total, weights) {
        if (!weights.length) return [];
        const remainder = distribute(
            total - weights.length,
            weights.map(value => Math.max(0, value - 1))
        );
        return remainder.map(value => value + 1);
    }

    function initialValues(items) {
        const bps = items.map(item => Number(item.bp || 0));
        const totalPercent = Math.min(100, Math.round(bps.reduce((sum, value) => sum + value, 0) / 100));
        if (!totalPercent) return evenValues(items.length);
        const floors = bps.map(value => Math.floor(value / 100));
        let left = totalPercent - floors.reduce((sum, value) => sum + value, 0);
        const order = bps.map((value, index) => ({ index, fraction: value % 100 }))
            .sort((a, b) => b.fraction - a.fraction || Number(items[a.index].id) - Number(items[b.index].id));
        for (let index = 0; index < left; index += 1) floors[order[index].index] += 1;
        return floors;
    }

    function sourceItems(root) {
        const selector = root.dataset.checkboxSelector;
        const nodes = selector
            ? Array.from(document.querySelectorAll(selector)).filter(node => node.checked)
            : Array.from(root.querySelectorAll('[data-allocation-item]'));
        return nodes.map(node => ({
            id: node.dataset.subprojectId,
            name: node.dataset.subprojectName,
            bp: Number(node.dataset.initialBp || 0)
        })).sort((a, b) => Number(a.id) - Number(b.id));
    }

    function initialise(root, resetEven) {
        const items = sourceItems(root);
        root.innerHTML = '';
        if (items.length < 2) {
            root.hidden = true;
            return;
        }
        root.hidden = false;
        const collapsible = root.dataset.collapsible === 'true';
        const rows = items.map((item, index) => ({
            ...item,
            value: (resetEven ? evenValues(items.length) : initialValues(items))[index],
            locked: false
        }));
        root.className = `attr${collapsible ? ' collapsed' : ' embedded open'}`;

        if (collapsible) {
            root.insertAdjacentHTML('beforeend',
                '<button type="button" class="attr-head" data-attr-head aria-expanded="false">' +
                '<span class="attr-chevron">&#9654;</span><span class="attr-head-label">Time split</span>' +
                '<span class="attr-head-summary" data-attr-summary></span>' +
                '<span class="attr-head-bar"><span class="attr-segbar mini" data-attr-minibar></span></span></button>');
        }
        root.insertAdjacentHTML('beforeend',
            '<div class="attr-body"><div class="attr-bar-top">' +
            '<span class="attr-state-tag" data-attr-tag><span class="dot"></span><span data-attr-tag-text></span></span>' +
            '<span class="attr-actions"><button type="button" class="attr-mini-btn" data-attr-even>' +
            '<i class="fa fa-bars" aria-hidden="true"></i> Distribute evenly</button></span></div>' +
            '<div class="attr-rows" data-attr-rows></div><div class="attr-segbar" data-attr-bar></div>' +
            '<div class="attr-foot"><span class="total">Total <b data-attr-total></b>%</span>' +
            '<span class="rem-note" data-attr-remainder></span></div></div>');

        const rowsElement = root.querySelector('[data-attr-rows]');
        rows.forEach((row, index) => {
            const element = document.createElement('div');
            element.className = 'attr-row';
            element.innerHTML = '<span class="attr-name"></span>' +
                '<input type="range" class="attr-slider" min="1" max="100" step="1" data-attr-slider>' +
                '<span class="attr-num"><input type="number" min="1" max="100" step="1" data-attr-number><span class="pct">%</span></span>' +
                '<button type="button" class="attr-lock" data-attr-lock aria-pressed="false"></button>' +
                `<input type="hidden" name="alloc_bp_${row.id}" data-attr-bp>`;
            element.querySelector('.attr-name').textContent = row.name;
            element.querySelector('.attr-name').title = row.name;
            rowsElement.appendChild(element);
            row.element = element;
            row.slider = element.querySelector('[data-attr-slider]');
            row.number = element.querySelector('[data-attr-number]');
            row.lock = element.querySelector('[data-attr-lock]');
            row.hidden = element.querySelector('[data-attr-bp]');
            row.slider.addEventListener('input', () => setValue(index, Number(row.slider.value)));
            row.number.addEventListener('change', () => setValue(index, Number(row.number.value)));
            row.number.addEventListener('keydown', event => {
                if (event.key === 'Enter') {
                    event.preventDefault();
                    setValue(index, Number(row.number.value));
                }
            });
            row.lock.addEventListener('click', () => {
                row.locked = !row.locked;
                render();
            });
        });

        function lockedSum() {
            return rows.reduce((sum, row) => sum + (row.locked ? row.value : 0), 0);
        }
        function total() {
            return rows.reduce((sum, row) => sum + row.value, 0);
        }
        function isEven() {
            const even = evenValues(rows.length);
            return !rows.some(row => row.locked) && rows.every((row, index) => row.value === even[index]);
        }
        function setValue(index, rawValue) {
            const row = rows[index];
            if (row.locked) return;
            const available = 100 - lockedSum();
            const others = rows.map((candidate, candidateIndex) => ({ candidate, candidateIndex }))
                .filter(item => item.candidateIndex !== index && !item.candidate.locked);
            const maximum = Math.max(1, available - others.length);
            row.value = clamp(Math.round(rawValue || 1), 1, maximum);
            if (others.length) {
                const values = distributePositive(available - row.value, others.map(item => item.candidate.value));
                others.forEach((item, valueIndex) => { item.candidate.value = values[valueIndex]; });
            }
            render();
        }
        function paintBar(element) {
            if (!element) return;
            element.innerHTML = '';
            rows.forEach((row, index) => {
                if (row.value <= 0) return;
                const segment = document.createElement('span');
                segment.className = 'attr-seg';
                segment.style.width = `${row.value}%`;
                segment.style.background = COLORS[index % COLORS.length];
                element.appendChild(segment);
            });
            const remainder = Math.max(0, 100 - total());
            if (remainder) {
                const segment = document.createElement('span');
                segment.className = 'attr-seg remainder';
                segment.style.width = `${remainder}%`;
                element.appendChild(segment);
            }
        }
        function render() {
            const allocated = total();
            const remainder = Math.max(0, 100 - allocated);
            rows.forEach((row, index) => {
                row.element.classList.toggle('locked', row.locked);
                row.slider.value = row.value;
                row.slider.disabled = row.locked;
                row.slider.style.background = `linear-gradient(90deg, ${COLORS[index % COLORS.length]} ${row.value}%, var(--border-dark) ${row.value}%)`;
                if (document.activeElement !== row.number) row.number.value = row.value;
                row.number.disabled = row.locked;
                row.lock.innerHTML = row.locked ? LOCK_CLOSED : LOCK_OPEN;
                row.lock.setAttribute('aria-pressed', String(row.locked));
                row.lock.title = row.locked ? 'Unlock this value' : 'Lock this value';
                row.hidden.value = row.value * 100;
            });
            const even = isEven();
            const tag = root.querySelector('[data-attr-tag]');
            tag.classList.toggle('custom', !even);
            root.querySelector('[data-attr-tag-text]').textContent = even ? 'Even split' : 'Custom split';
            root.querySelector('[data-attr-total]').textContent = allocated;
            const remainderElement = root.querySelector('[data-attr-remainder]');
            remainderElement.textContent = remainder ? `${remainder}% unallocated (no subproject)` : 'Fully allocated';
            remainderElement.classList.toggle('zero', !remainder);
            paintBar(root.querySelector('[data-attr-bar]'));
            paintBar(root.querySelector('[data-attr-minibar]'));
            const summary = root.querySelector('[data-attr-summary]');
            if (summary) summary.textContent = `${even ? 'Even split' : 'Custom'} · ${rows.map(row => row.value).join(' / ')}${remainder ? ` · ${remainder}% unallocated` : ''}`;
        }

        root.querySelector('[data-attr-even]').addEventListener('click', () => {
            const values = evenValues(rows.length);
            rows.forEach((row, index) => { row.value = values[index]; row.locked = false; });
            render();
        });
        const head = root.querySelector('[data-attr-head]');
        if (head) head.addEventListener('click', () => {
            const open = root.classList.toggle('open');
            root.classList.toggle('collapsed', !open);
            head.setAttribute('aria-expanded', String(open));
        });
        render();
    }

    document.addEventListener('DOMContentLoaded', () => {
        document.querySelectorAll('[data-allocation-editor]').forEach(root => {
            initialise(root, false);
            const selector = root.dataset.checkboxSelector;
            if (selector) document.addEventListener('change', event => {
                if (event.target.matches(selector)) initialise(root, true);
            });
        });
    });
})();
