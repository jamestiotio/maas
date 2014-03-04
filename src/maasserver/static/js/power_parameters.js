/* Copyright 2012-2014 Canonical Ltd.  This software is licensed under the
 * GNU Affero General Public License version 3 (see the file LICENSE).
 *
 * Power parameters utilities.
 *
 * @module Y.maas.power_parameter
 */

YUI.add('maas.power_parameters', function(Y) {

Y.log('loading maas.power_parameters');
var module = Y.namespace('maas.power_parameters');

// Only used to mockup io in tests.
module._io = new Y.IO();

var LinkedContentWidget;

/**
 * A widget class used to have the content of a node dependent of the selected
 * value of a <select> tag.
 *
 */
LinkedContentWidget = function() {
    LinkedContentWidget.superclass.constructor.apply(this, arguments);
};

LinkedContentWidget.NAME = 'dynamic-widget';

Y.extend(LinkedContentWidget, Y.Widget, {

   /**
    * Initialize the widget.
    * - cfg.srcNode is the  node which will be updated when the selected
    *   value of the 'driver node' will change.
    * - cfg.driverNode is the node containing a 'select' element.  When
    *   the selected element will change, the srcNode HTML will be
    *   updated.
    * - cfg.driverEnum is an array containing all possible values for the
    *   driverNode's select element.  Each value will have its own template to
    *   define additional parameter fields.  For example, each power type has
    *   its own set of power parameter fields, as defined by a template for
    *   that power type.  Selecting a power type on a node's edit page will
    *   reveal input fields for the power parameters associated with that power
    *   type.  Each power type has a template with an HTML ID like
    *   "power-parameter-form-<power type>" to define its power parameters.
    *   The templates are defined as script entries with a MIME type of
    *   "text/x-template".
    * - cfg.templatePrefix is a CSS selector prefix.  It will be used to select
    *   the templates for the respective enumeration values defined in
    *   driverEnum.
    *
    * @method initializer
    */
    initializer: function(cfg) {
        this.driverEnum = cfg.driverEnum;
        this.templatePrefix = cfg.templatePrefix;
        this.initTemplates();
    },

   /**
    * Create a dictionary containing the respective templates for all values
    * in 'this.driverEnum'.
    *
    * @method initTemplates
    */
    initTemplates: function() {
        var counter;
        this.templates = {};
        for (counter = 0; counter < this.driverEnum.length; counter++) {
            var driver = this.driverEnum[counter];
            var template = Y.one(this.templatePrefix + driver).getContent();
            this.templates[driver] = template;
        }
    },

   /**
    * Bind the widget to events (ot name 'evnt_name') generated by the given
    * 'driverNode'.
    *
    * @method bindTo
    */
    bindTo: function(driverNode, event_name) {
        var self = this;
        Y.one(driverNode).on(event_name, function(e) {
            var newDriverValue = e.currentTarget.get('value');
            self.switchTo(newDriverValue);
        });
        var driverValue = driverNode.get('value');
        this.setVisibility(driverValue);
    },
   /**
    * Hide 'srcNode' if the value of the 'driverNode' is the empty string
    * and show it otherwise.
    *
    * @method setVisibility
    */
    setVisibility: function(driverValue) {
        if (driverValue === '') {
            this.get('srcNode').addClass('hidden');
        }
        else {
            this.get('srcNode').removeClass('hidden');
        }
    },

   /**
    * React to a new value of the driver node: update the HTML of
    * 'srcNode'.
    *
    * @method switchTo
    */
    switchTo: function(newDriverValue) {
        // Remove old fieldset if any.
        var srcNode = this.get('srcNode');
        srcNode.all('fieldset').remove();
        // Insert the template fragment corresponding to the new value
        // of the driver in 'srcNode'.
        var old_innerHTML = srcNode.get('innerHTML');
        srcNode.set(
            'innerHTML', old_innerHTML + this.templates[newDriverValue]);
        this.setVisibility(newDriverValue);
    }

});

module.LinkedContentWidget = LinkedContentWidget;

}, '0.1', {'requires': ['widget', 'io', 'maas.enums']}
);
