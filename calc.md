This protocol defines the mathematical logic for calculating shot adjustments in the "GunBound" environment.

### **1. Input Variables & Global Functions**
* $W$: Integer. Wind strength (0–26).
* $\theta$: Float. Wind direction in degrees.
    * $0^{\circ}$ = Vertical Up (North).
    * $90^{\circ}$ = Horizontal Right (East/Towards Enemy).
    * $-90^{\circ}$ = Horizontal Left (West/Against You).
    * $\pm180^{\circ}$ = Vertical Down (South).
* $f(x) = \lfloor x \rfloor$: All division operations must be **floored** to the nearest integer.

---

### **2. Execution Mode: Vertical Axis (Power Modification)**
When the wind vector is purely vertical, angle remains static. Adjust shot power (bars) only.

* **Case $\theta = 0^{\circ}$ (Wind Up):**
    * `Power_Adjustment = - (f(W / 7) * 0.1)`
* **Case $\theta = \pm180^{\circ}$ (Wind Down):**
    * `Power_Adjustment = + (f(W / 7) * 0.1)`

---

### **3. Execution Mode: Angular Calculation (Angle Modification)**
Map the wind angle $\theta$ to the following logic gates. "Adjustment" refers to the change in aiming degrees.

#### **Quadrant: Upper Left ($-90^{\circ} < \theta < 0^{\circ}$)**
**Symbol: Grey $**$**
* **Vector Range $[-80^{\circ}, -10^{\circ}]$:**
    * Identify divisor $D$ by visual proximity: $D \in \{3, 5, 7, 10, 20\}$.
    * **If $D = 3$:**
        * `Base = f(W / 3)`
        * `If W <= 12: Adjustment = Base`
        * `If W >= 13: Adjustment = Base + 1`
        * `If W \in \{25, 26\}: Adjustment = Base + 2`
    * **Else ($D \neq 3$):**
        * `Adjustment = f(W / D)`

#### **Quadrant: Upper Right ($0^{\circ} < \theta < 90^{\circ}$)**
**Symbol: Black $**$ (Red Arrow Range $\approx 30^{\circ}$ to $45^{\circ}$)**
* `Base = f(W / 2)`
* `If W > 7: Adjustment = Base + 1`
* `If W > 18: Adjustment = Base + 2`

**Symbol: Grey $*$ (Grey Arrow Range $\approx 60^{\circ}$ to $75^{\circ}$)**
* `Step1 = f(W / 2)`
* `Step2 = f(Step1 / 2)`
* `Base = Step1 + Step2`
* `If W < 12: Adjustment = Base`
* `Else: Adjustment = Base - 1`

#### **Quadrant: Bottom Left ($-180^{\circ} < \theta < -90^{\circ}$)**
**Symbol: Red $*$ (Red Arrow Range $\approx -110^{\circ}$ to $-140^{\circ}$)**
* `Base = f(W / 2)`
* `If W <= 10: Adjustment = Base`
* `Else: Adjustment = Base + 1`

**Standard Range (Red Arrow $\approx -155^{\circ}$)**
* `Adjustment = f(W / 4)`

#### **Quadrant: Bottom Right ($90^{\circ} < \theta < 180^{\circ}$)**
**Symbol: Red $**$ (Red Arrow Range $\approx 110^{\circ}$ to $140^{\circ}$)**
* `Base = f(W / 2)`
* `If W < 22: Adjustment = Base - 1`
* `Else: Adjustment = Base - 2`

**Symbol: Blue $*$ ("Tricky Wind" $\approx 150^{\circ}$)**
* `If Distance = Long: Adjustment = 0`
* `If Distance = Short: Adjustment = f(W / 4)`

**Symbol: Blue $**$ ($\approx 165^{\circ}$)**
* `Adjustment = f(W / 2) + f(W / 10)`
    * *Note: This represents 40% of total wind force. Inversely scale with shot distance.*

---

### **4. Horizontal Baseline**
**Target: $\theta = 90^{\circ}$ or $\theta = -90^{\circ}$**
* **Rule:** Standard division.
* `Adjustment = f(W / 2)`

---

### **5. Summary Table for Programmatic Mapping**

| Logic Gate | Angle Range ($\theta$) | Primary Formula | Secondary Modifiers |
| :--- | :--- | :--- | :--- |
| **Grey $**$** | $-80^{\circ}$ to $-10^{\circ}$ | $W / D$ | Penalty for $W \ge 13$ at $D=3$ |
| **Black $**$** | $30^{\circ}$ to $45^{\circ}$ | $W / 2$ | $+1$ if $W>7$, $+2$ if $W>18$ |
| **Grey $*$** | $60^{\circ}$ to $75^{\circ}$ | $(W/2) + (W/4)$ | $-1$ if $W \ge 12$ |
| **Red $*$** | $-110^{\circ}$ to $-140^{\circ}$ | $W / 2$ | $+1$ if $W > 10$ |
| **Red $**$** | $110^{\circ}$ to $140^{\circ}$ | $W / 2$ | $-1$ (base) or $-2$ if $W \ge 22$ |
| **Blue $*$** | $150^{\circ}$ | Distance Scaled | Far = $0$, Near = $W/4$ |
| **Blue $**$** | $165^{\circ}$ | $0.4 \times W$ | $(W/2) + (W/10)$ |