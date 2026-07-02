# Arquitectura — sistema agéntico CAD → código máquina

## 1. Objetivo

Convertir la información de fabricación de una pieza (modelo 3D, plano 2D acotado)
en un programa CNC listo para revisar, para cualquier máquina del taller.

- **MVP (hoy):** `.step` → G-code Fanuc para Doosan DNM 5700 (centro vertical 3 ejes),
  operaciones de taladrado.
- **Cliente piloto:** programa hoy con NX CAM (Siemens). El STEP de entrada sale de NX,
  y el plano 2D en PDF también. A futuro el sistema debe leer ese plano (cotas,
  tolerancias, acabados) porque el STEP solo lleva geometría, no intención de diseño.

## 2. Principio de diseño: modelo intermedio

La clave para "cualquier entrada → cualquier máquina" es no acoplar nunca el formato
de entrada con el dialecto de salida. Todo pasa por un **modelo intermedio de
features de fabricación** (`cad2gcode/features/model.py`):

```
PartModel
├── stock / caja envolvente (material en bruto)
├── material ("aluminio", "acero", ...)
└── features
    ├── Hole      (posición, diámetro, profundidad, pasante o ciego, ¿roscado?)
    ├── Pocket    (contorno, profundidad)          ← definido, sin detección aún
    └── Contour   (perfil exterior, profundidad)   ← definido, sin detección aún
```

Esto es deliberadamente parecido a lo que hace NX CAM internamente (feature-based
machining): el agente razona sobre *features de mecanizado*, no sobre triángulos ni
sobre líneas de G-code.

## 3. Capas

### 3.1 Readers (`cad2gcode/readers/`)

Convierten un archivo en un `PartModel`. Cada reader declara qué extensiones acepta.

- **`step_reader.py` (MVP):** parser propio de STEP Part 21 (ISO 10303-21), sin
  dependencias. Extrae `CARTESIAN_POINT`, `DIRECTION`, `AXIS2_PLACEMENT_3D`,
  `CYLINDRICAL_SURFACE` y `CIRCLE`, y con eso:
  - caja envolvente de la pieza (de la nube de puntos),
  - agujeros: superficies cilíndricas con eje paralelo a Z; el diámetro sale del
    radio, la posición del eje, y la profundidad de la extensión en Z de los
    círculos/aristas asociados al mismo eje (si no es determinable, se asume
    pasante = espesor de la pieza y se marca `verified=False` para revisión).

  *Limitación asumida:* no es un kernel B-rep. Para piezas prismáticas taladradas
  funciona; para geometría compleja el plan es migrar a OpenCascade (`pythonocc-core`
  / `build123d`) manteniendo la misma interfaz `Reader`.

- **Futuro:** `dxf_reader` (planos 2D), `pdf_reader` (plano escaneado → visión con
  Claude para extraer cotas y tolerancias — es la pieza que convierte esto en un
  sistema "que lee planos" de verdad).

### 3.2 Base de conocimiento de máquinas (`cad2gcode/knowledge/`)

Un JSON por máquina: carreras, husillo, cono, cambiador, dialecto de control y
particularidades del post. `doosan_dnm5700.json` es la referencia. Añadir una
máquina no toca código: se añade el JSON y (si el control es nuevo) un postprocesador.

### 3.3 Planner (`cad2gcode/planner/`)

Convierte `PartModel` + máquina + material en un `ProcessPlan` (lista ordenada de
operaciones con herramienta, régimen de corte y ciclo).

Dos implementaciones intercambiables:

- **`rules.py` — determinista (por defecto).** Para el MVP de taladrado:
  agrupa agujeros por diámetro, antepone centrado, elige G81 (profundidad ≤ 3×D)
  o G83 con rotura de viruta (Q = D/2) para agujero profundo, y calcula S y F a
  partir de una tabla de datos de corte por material (Vc y avance por vuelta).
  Sirve de línea base verificable y de red de seguridad sin API.

- **`agent.py` — agéntico (opcional, `--agent`).** Un agente sobre la API de Claude
  (`claude-opus-4-8`, razonamiento adaptativo) con herramientas:
  - `get_machine_spec` — consulta la ficha de la máquina,
  - `get_cutting_data` — tabla de datos de corte,
  - `submit_plan` — entrega el plan final validado contra el mismo esquema
    (`ProcessPlan`) que usa el planificador por reglas.

  El agente decide secuencia, agrupación de herramientas y regímenes justificando
  sus elecciones; el harness **valida** el plan (límites de máquina, herramientas
  coherentes, profundidades alcanzables) antes de postprocesar. Si la validación
  falla o no hay credenciales, se degrada al planificador por reglas.

  Este es el punto donde el sistema escala en inteligencia: tolerancias del plano →
  elección de escariado/mandrinado, acabados → pasadas de acabado, amarres, etc.

### 3.4 Postprocessors (`cad2gcode/postprocessors/`)

Convierten `ProcessPlan` en texto de programa para un control concreto.

- **`doosan_dnm5700.py` (MVP):** dialecto Fanuc i. Cabecera segura
  (G90 G17 G21 G40 G49 G80), G54, cambio de herramienta con G43 H, ciclos fijos
  G81/G83, retirada G91 G28, M30. Verifica que cada punto cae dentro de las
  carreras de la máquina y que S no supera el husillo.
- **Futuro:** `siemens_840d.py` (ShopMill/DIN, relevante porque el cliente usa NX y
  Siemens), `heidenhain.py`, etc.

### 3.5 CLI (`cad2gcode/cli.py`)

`convert` (pipeline completo) e `inspect` (solo lectura de features, para depurar
la interpretación del STEP antes de fiarse del código).

## 4. Flujo agéntico completo (visión)

```
plano PDF + STEP ──▶ agente lector (visión: cotas, tolerancias, material, rugosidades)
                        │
                        ▼
                 PartModel enriquecido (feature + tolerancia + acabado)
                        │
                        ▼
                 agente planificador (proceso, herramientas, amarres, fases)
                        │                      ▲
                        ▼                      │ herramientas: specs máquina,
                 validador determinista ───────┘ catálogo de herramientas del taller,
                        │                        datos de corte, histórico de piezas
                        ▼
                 postprocesador máquina destino
                        │
                        ▼
                 programa CNC + hoja de proceso + avisos para el programador
```

Reglas del sistema:

1. **El LLM nunca escribe G-code directamente.** Propone un plan estructurado; el
   G-code lo emite siempre un postprocesador determinista y verificable. Esto acota
   el riesgo: un plan malo se detecta en validación, no en la máquina.
2. **Todo plan lleva trazabilidad:** qué feature origina cada operación y por qué se
   eligió cada régimen (el agente lo justifica en el plan).
3. **Humano en el bucle:** la salida es "programa para revisar", no "programa para
   ejecutar". La simulación (NX/Vericut) sigue siendo obligatoria.

## 5. Perfil del cliente piloto (actualizado)

Mecanizado **de precisión**, piezas de **superficies 3D** (no prismáticas),
máquinas de **3 ejes**, programación actual con **NX CAM (Siemens)**.

Consecuencias de diseño:

1. **Las trayectorias de superficie de precisión las calcula NX, no nosotros.**
   Control de cresta, suavizado y calidad de acabado a nivel de micras son el
   corazón de un CAM comercial; reimplementarlos no es viable ni genera confianza
   en taller. El valor del agente está en eliminar el tiempo de programación,
   no en sustituir el motor de trayectorias.
2. **El núcleo del sistema pasa a ser un agente que programa NX vía NXOpen
   (Python):** carga el `.prt` (con PMI: tolerancias y acabados anotados),
   decide estrategia (fases, amarres, desbaste/semiacabado/acabado, operación NX
   por zona, herramientas y regímenes), materializa el plan en NX reutilizando
   las plantillas del taller, NX genera y verifica las trayectorias, y el post
   oficial emite el programa.
3. **3 ejes simplifica el problema** (sin cinemática rotativa) y habilita una
   **vía experimental propia**: OpenCascade (B-rep del STEP) + OpenCAMLib
   (desbaste por niveles Z, acabado raster/waterline por drop-cutter) + nuestro
   post Fanuc. Sirve para desbastes, piezas no críticas y como banco de pruebas
   del agente sin licencias — no para el acabado de precisión.

```
                       ┌──────────────────────────────────────────────┐
   .prt / STEP+plano ─▶│ agente planificador (este repo: planner/)     │
                       └───────┬──────────────────────────┬───────────┘
                               │ vía principal            │ vía experimental
                               ▼                          ▼
                    NX CAM vía NXOpen              OpenCAMLib (3 ejes)
                    (trayectorias + verificación)  (desbaste/acabado básico)
                               │                          │
                               ▼                          ▼
                    post oficial NX                postprocessors/ (este repo)
                               └──────────┬───────────────┘
                                          ▼
                            programa CNC + hoja de proceso
```

El pipeline de taladrado del MVP queda como caso simple y banco de pruebas de
la cadena completa (reader → planner → validación → post).

## 6. Roadmap técnico (revisado para superficies 3D / 3 ejes)

1. **v0 (este repo):** taladrado STEP → DNM 5700, planner reglas + agente,
   validación determinista, tests. Demuestra la arquitectura.
2. **v0.2 — descubrimiento NX:** confirmar licencia NXOpen del piloto,
   inventariar sus plantillas/operaciones NX y su histórico de piezas; prototipo
   NXOpen mínimo (abrir .prt, listar geometría y PMI, crear una operación desde
   plantilla, generar trayectoria, postprocesar).
3. **v0.3 — agente sobre NX:** el planner produce un plan de proceso (mismo
   esquema validable de hoy) y un ejecutor NXOpen lo materializa en NX.
   Benchmark de aceptación: comparar contra programas reales del taller.
4. **v0.4 — lectura de intención:** PMI del .prt y/o plano PDF con visión
   (tolerancias → elección de estrategia y acabados); hoja de proceso.
5. **v0.5 — vía experimental 3 ejes:** OpenCascade + OpenCAMLib para desbaste y
   acabado básico con nuestro post (G01 punto a punto ya soportable en el post).
6. **v1:** amarres y fases múltiples, memoria del agente sobre el histórico del
   taller, más máquinas/postes.
