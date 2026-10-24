/*
 * Rule builder for the Rule.combination admin field.
 * The JSON textarea stays the form value: the builder rewrites it on every
 * change, and editing the JSON by hand re-renders the builder. The server
 * validator (rules.validate_combination) is the source of truth.
 */
(function () {
  "use strict";

  const TYPE_LABELS = {
    number: "Numbers",
    time: "Time of day",
    datetime: "Date & time",
  };
  const PATTERNS = {
    time: /^\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/,
    datetime: /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/,
  };
  const LOCAL_DATETIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$/;

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function opOf(node) {
    if (node && typeof node === "object" && !Array.isArray(node)) {
      const keys = Object.keys(node);
      if (keys.length === 1) return keys[0];
    }
    return null;
  }

  function option(spec) {
    const node = el("option", null, spec.label);
    node.value = spec.value;
    if (spec.title) node.title = spec.title;
    return node;
  }

  // options: [{value, label}] or [{group, options: [{value, label}]}]
  function select(options, value, onChange) {
    const node = el("select", "rb-select");
    for (const spec of options) {
      if (spec.options) {
        const group = el("optgroup");
        group.label = spec.group;
        spec.options.forEach((o) => group.append(option(o)));
        node.append(group);
      } else {
        node.append(option(spec));
      }
    }
    node.value = value;
    node.addEventListener("change", () => onChange(node.value));
    return node;
  }

  function button(label, onClick, className) {
    const node = el("button", "rb-button" + (className ? " " + className : ""), label);
    node.type = "button";
    node.addEventListener("click", onClick);
    return node;
  }

  function init(container) {
    const input = document.getElementById(container.dataset.input);
    const catalog = JSON.parse(
      document.getElementById(container.dataset.catalog).textContent
    );
    const treeBox = container.querySelector(".rule-builder__tree");
    const preview = container.querySelector(".rule-builder__preview");
    const fields = new Map(catalog.fields.map((f) => [f.name, f]));
    const operators = new Map(catalog.operators.map((o) => [o.op, o]));
    const ofKind = (...kinds) =>
      catalog.operators.filter((o) => kinds.includes(o.kind));
    let root = { and: [] };

    // --- types and defaults -------------------------------------------

    function isArithmetic(op) {
      return operators.has(op) && operators.get(op).kind === "arithmetic";
    }

    // Constants (strings) have no type of their own: they take the
    // type of the other side of the comparison.
    function typeOf(node) {
      const op = opOf(node);
      if (op === "field") {
        return fields.has(node.field) ? fields.get(node.field).type : null;
      }
      if (isArithmetic(op) || typeof node === "number") return "number";
      return null;
    }

    function firstField(type) {
      for (const field of fields.values()) {
        if (field.type === type) return field;
      }
      return catalog.fields[0];
    }

    function defaultConstant(type) {
      if (type === "time") return "12:00";
      if (type === "datetime") {
        return new Date().toISOString().slice(0, 10) + "T00:00";
      }
      return 0;
    }

    function fitsType(constant, type) {
      if (type === "number") return typeof constant === "number";
      return typeof constant === "string" && PATTERNS[type].test(constant);
    }

    function defaultCondition() {
      return { ge: [{ field: firstField("number").name }, 0] };
    }

    // Keep a condition consistent after its left side changed type.
    function normalize(condition) {
      const op = opOf(condition);
      const args = condition[op];
      const type = typeOf(args[0]) || typeOf(args[1]) || "number";
      if (!operators.get(op).types.includes(type)) {
        delete condition[op];
        condition.eq = [args[0], defaultConstant(type)];
        return;
      }
      if (op === "in") {
        const kept = args[1].filter((c) => fitsType(c, type));
        args[1] = kept.length ? kept : [defaultConstant(type)];
        return;
      }
      const rightType = typeOf(args[1]);
      if (rightType ? rightType !== type : !fitsType(args[1], type)) {
        args[1] = defaultConstant(type);
      }
    }

    // --- rendering ------------------------------------------------------

    function render() {
      treeBox.replaceChildren(renderBool(root, (node) => (root = node), null));
    }

    function sync() {
      input.value = JSON.stringify(root, null, 2);
      preview.textContent = describe(root);
    }

    function changed() {
      render();
      sync();
    }

    function renderBool(node, set, remove) {
      const negated =
        opOf(node) === "not" && Array.isArray(node.not) && node.not.length === 1;
      const inner = negated ? node.not[0] : node;
      const setInner = negated ? (n) => set({ not: [n] }) : set;
      const box = el("div", "rb-node" + (negated ? " rb-node--negated" : ""));
      const op = opOf(inner);
      const spec = operators.get(op);
      const args = op ? inner[op] : null;
      let body;
      if ((op === "and" || op === "or") && Array.isArray(args)) {
        body = renderGroup(inner, setInner);
      } else if (
        spec &&
        ["comparison", "membership"].includes(spec.kind) &&
        Array.isArray(args) &&
        args.length === 2 &&
        (op !== "in" || Array.isArray(args[1]))
      ) {
        body = renderCondition(inner);
      } else {
        body = renderUnknown(inner);
      }
      const tools = el("div", "rb-tools");
      const notLabel = el("label", "rb-not");
      const checkbox = el("input");
      checkbox.type = "checkbox";
      checkbox.checked = negated;
      checkbox.addEventListener("change", () => {
        set(checkbox.checked ? { not: [inner] } : inner);
        changed();
      });
      notLabel.append(checkbox, " NOT");
      tools.append(notLabel);
      if (remove) {
        tools.append(
          button("✕", () => {
            remove();
            changed();
          }, "rb-button--remove")
        );
      }
      box.append(body, tools);
      return box;
    }

    function renderGroup(group, set) {
      const op = opOf(group);
      const children = group[op];
      const box = el("div", "rb-group");
      const header = el("div", "rb-group__header");
      header.append(
        select(
          [
            { value: "and", label: "ALL of" },
            { value: "or", label: "ANY of" },
          ],
          op,
          (value) => {
            set({ [value]: children });
            changed();
          }
        ),
        el(
          "span",
          "rb-hint",
          op === "and" ? "every condition must hold" : "one condition is enough"
        )
      );
      const list = el("div", "rb-group__children");
      children.forEach((child, i) => {
        list.append(
          renderBool(
            child,
            (n) => (children[i] = n),
            () => children.splice(i, 1)
          )
        );
      });
      if (!children.length) {
        list.append(el("p", "rb-hint", "No conditions yet."));
      }
      const actions = el("div", "rb-group__actions");
      actions.append(
        button("+ Condition", () => {
          children.push(defaultCondition());
          changed();
        }),
        button("+ Group", () => {
          children.push({ [op === "and" ? "or" : "and"]: [defaultCondition()] });
          changed();
        })
      );
      box.append(header, list, actions);
      return box;
    }

    function renderCondition(condition) {
      const op = opOf(condition);
      const args = condition[op];
      const type = typeOf(args[0]) || typeOf(args[1]) || "number";
      const box = el("div", "rb-condition");
      box.append(
        renderValue(
          args[0],
          (n) => {
            args[0] = n;
            normalize(condition);
          },
          null,
          false
        )
      );
      const allowed = ofKind("comparison", "membership").filter((o) =>
        o.types.includes(type)
      );
      box.append(
        select(
          allowed.map((o) => ({ value: o.op, label: o.symbol })),
          op,
          (value) => {
            let right = args[1];
            if (op === "in") right = args[1][0];
            if (value === "in") {
              right = [fitsType(right, type) ? right : defaultConstant(type)];
            }
            delete condition[op];
            condition[value] = [args[0], right];
            changed();
          }
        )
      );
      if (op === "in") {
        box.append(renderList(args[1], type));
      } else {
        box.append(renderValue(args[1], (n) => (args[1] = n), type, true));
      }
      return box;
    }

    function renderValue(node, set, partnerType, allowConstant) {
      const box = el("span", "rb-value");
      const op = opOf(node);
      let kind = "unknown";
      if (op === "field") kind = "field";
      else if (isArithmetic(op) && Array.isArray(node[op]) && node[op].length === 2) {
        kind = "calc";
      } else if (typeof node === "number" || typeof node === "string") {
        kind = "constant";
      }
      if (kind === "unknown") {
        box.append(renderUnknown(node));
        return box;
      }
      const kinds = [{ value: "field", label: "field" }];
      if (allowConstant || kind === "constant") {
        kinds.push({ value: "constant", label: "value" });
      }
      if (!partnerType || partnerType === "number") {
        kinds.push({ value: "calc", label: "calculation" });
      }
      box.append(
        select(kinds, kind, (value) => {
          const type = partnerType || typeOf(node) || "number";
          if (value === "field") set({ field: firstField(type).name });
          else if (value === "constant") set(defaultConstant(type));
          else set({ add: [{ field: firstField("number").name }, 0] });
          changed();
        })
      );
      if (kind === "field") {
        box.append(
          fieldSelect(node.field, partnerType, (name) => {
            set({ field: name });
            changed();
          })
        );
        const field = fields.get(node.field);
        if (field && field.description) {
          box.append(el("span", "rb-hint", field.description));
        }
      } else if (kind === "constant") {
        box.append(
          constantInput(node, partnerType || "number", (value) => {
            set(value);
            sync();
          })
        );
      } else {
        const args = node[op];
        const calc = el("span", "rb-calc");
        calc.append(
          "(",
          renderValue(args[0], (n) => (args[0] = n), "number", true),
          select(
            ofKind("arithmetic").map((o) => ({ value: o.op, label: o.symbol })),
            op,
            (value) => {
              set({ [value]: args });
              changed();
            }
          ),
          renderValue(args[1], (n) => (args[1] = n), "number", true),
          ")"
        );
        box.append(calc);
      }
      return box;
    }

    function fieldSelect(value, type, onChange) {
      const groups = [];
      if (!fields.has(value)) {
        groups.push({ value: value, label: value + " (unknown field)" });
      }
      for (const [fieldType, label] of Object.entries(TYPE_LABELS)) {
        if (type && fieldType !== type) continue;
        const options = catalog.fields
          .filter((f) => f.type === fieldType)
          .map((f) => ({
            value: f.name,
            label: f.name + (f.nullable ? " (may be empty)" : ""),
            title: f.description || "",
          }));
        if (options.length) groups.push({ group: label, options: options });
      }
      return select(groups, value, onChange);
    }

    function constantInput(value, type, onInput) {
      const node = el("input", "rb-input");
      node.value = value === undefined || value === null ? "" : String(value);
      if (type === "number") {
        node.type = "number";
        node.step = "any";
        node.addEventListener("input", () => {
          if (node.value !== "" && !Number.isNaN(node.valueAsNumber)) {
            onInput(node.valueAsNumber);
          }
        });
        return node;
      }
      if (type === "time") {
        node.type = "time";
      } else {
        // datetime-local cannot show an offset; keep text for such values.
        const local = !node.value || LOCAL_DATETIME.test(node.value);
        node.type = local ? "datetime-local" : "text";
      }
      node.addEventListener("input", () => {
        if (node.value) onInput(node.value);
      });
      return node;
    }

    function renderList(list, type) {
      const node = el("input", "rb-input rb-input--list");
      node.type = "text";
      node.placeholder = type === "time" ? "08:00, 12:00" : "0, 1, 2";
      node.value = list.join(", ");
      node.addEventListener("input", () => {
        const items = node.value
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean);
        const parsed =
          type === "number"
            ? items.map(Number).filter((n) => !Number.isNaN(n))
            : items;
        list.splice(0, list.length, ...parsed);
        sync();
      });
      return node;
    }

    function renderUnknown(node) {
      const box = el("span", "rb-unknown");
      box.append(
        el("code", null, JSON.stringify(node)),
        el("span", "rb-hint", "edit it in the JSON below")
      );
      return box;
    }

    // --- preview (mirrors rules.describe) -------------------------------

    function describe(node, top = true) {
      const op = opOf(node);
      const args = op ? node[op] : null;
      if ((op === "and" || op === "or") && Array.isArray(args)) {
        if (!args.length) return "(no conditions)";
        const symbol = ` ${operators.get(op).symbol} `;
        const text = args.map((arg) => describe(arg, false)).join(symbol);
        return top || args.length === 1 ? text : `(${text})`;
      }
      if (op === "not" && Array.isArray(args)) {
        return `NOT (${describe(args[0], true)})`;
      }
      if (op === "in" && Array.isArray(args) && Array.isArray(args[1])) {
        return `${describeValue(args[0])} in [${args[1].join(", ")}]`;
      }
      if (operators.has(op) && Array.isArray(args) && args.length === 2) {
        const symbol = operators.get(op).symbol;
        return `${describeValue(args[0])} ${symbol} ${describeValue(args[1])}`;
      }
      return JSON.stringify(node);
    }

    function describeValue(node) {
      const op = opOf(node);
      if (op === "field") return node.field;
      if (isArithmetic(op) && Array.isArray(node[op])) {
        const [left, right] = node[op];
        const symbol = operators.get(op).symbol;
        return `(${describeValue(left)} ${symbol} ${describeValue(right)})`;
      }
      return typeof node === "object" ? JSON.stringify(node) : String(node);
    }

    // --- wiring -----------------------------------------------------------

    input.addEventListener("input", () => {
      let parsed;
      try {
        parsed = JSON.parse(input.value);
      } catch (e) {
        parsed = null;
      }
      if (opOf(parsed)) {
        root = parsed;
        render();
        preview.textContent = describe(root);
      } else {
        preview.textContent =
          "The JSON is not a rule yet; the builder shows the last valid one.";
      }
    });

    let stored;
    try {
      stored = JSON.parse(input.value);
    } catch (e) {
      stored = undefined;
    }
    const op = opOf(stored);
    if (op) {
      // A bare condition becomes a one-item ALL group, which means the
      // same and gives the builder somewhere to add conditions.
      root = ["and", "or", "not"].includes(op) ? stored : { and: [stored] };
      changed();
    } else {
      render();
      if (stored === null || input.value.trim() === "") {
        preview.textContent = "Add conditions to build the rule.";
      } else {
        preview.textContent =
          "The stored JSON is not a rule; fix it below or rebuild it here.";
        container.querySelector(".rule-builder__raw").open = true;
      }
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".rule-builder").forEach(init);
  });
})();
