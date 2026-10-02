(function () {
    var providerSelect = document.getElementById('AI_PROVIDER');
    var selects = document.querySelectorAll('#AI_MODEL, select[name="model"]');
    Array.prototype.forEach.call(selects, function (select) {
        var status = document.createElement('div');
        status.setAttribute('role', 'status');
        status.style.cssText = 'font-size:0.85em;margin-top:4px;overflow-wrap:anywhere;';
        select.parentNode.insertBefore(status, select.nextSibling);
        select.style.maxWidth = '100%';
        var requestNumber = 0;

        function loadModels(reset) {
            var provider = providerSelect ? providerSelect.value : select.getAttribute('data-provider');
            var selected = reset ? '' : select.value;
            var defaultLabel = select.options[0].text;
            var currentRequest = ++requestNumber;
            if (reset) {
                select.options.length = 0;
                select.add(new Option(defaultLabel, ''));
            }
            status.textContent = 'Loading models...';
            status.style.color = '#aaa';
            fetch('/api/models?provider=' + encodeURIComponent(provider))
                .then(function (response) {
                    return response.json().then(function (data) {
                        if (!response.ok) throw new Error(data.error || 'Unable to load models.');
                        return data;
                    });
                })
                .then(function (data) {
                    if (currentRequest !== requestNumber) return;
                    select.options.length = 0;
                    select.add(new Option(defaultLabel, ''));
                    var found = false;
                    data.models.forEach(function (model) {
                        select.add(new Option(model.name + ' (' + model.id + ')', model.id));
                        if (model.id === selected) found = true;
                    });
                    if (selected && !found) select.add(new Option(selected, selected));
                    select.value = selected;
                    status.textContent = selected && !found ? 'Selected model is not in the provider catalog.' : '';
                    status.style.color = '#ff8888';
                })
                .catch(function (error) {
                    if (currentRequest !== requestNumber) return;
                    status.textContent = error.message || 'Unable to load models. Check your connection.';
                    status.style.color = '#ff8888';
                });
        }

        if (providerSelect) providerSelect.addEventListener('change', function () { loadModels(true); });
        loadModels(false);
    });
}());