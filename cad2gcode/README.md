# cad2gcode — Sistema agéntico CAD → código máquina

Sistema local que lee modelos/planos de piezas y genera el programa CNC para la máquina destino.

**MVP:** archivo `.step` (exportado desde NX Siemens) → programa G-code (dialecto Fanuc) para **Doosan DNM 5700**, limitado a operaciones de taladrado en piezas prismáticas.

**Visión:** cualquier formato de entrada (STEP, DXF, PDF de plano con cotas) → cualquier máquina (Fanuc, Siemens 840D, Heidenhain...), con un agente experto en mecanizado tomando las decisiones de proceso.

## Arquitectura (resumen)

```
 entrada            modelo intermedio          planificación            salida
┌─────────┐        ┌──────────────────┐       ┌──────────────┐       ┌──────────────────┐
│ readers │──────▶ │ PartModel        │─────▶ │ planner      │─────▶ │ postprocessors   │
│ (.step) │        │ (features:       │       │ (reglas o    │       │ (doosan_dnm5700, │
│ (.dxf)* │        │  agujeros,       │       │  agente      │       │  siemens_840d*)  │
│ (.pdf)* │        │  cajeras*, ...)  │       │  Claude)     │       │                  │
└─────────┘        └──────────────────┘       └──────────────┘       └──────────────────┘
                                                                      * = futuro
```

Cada capa es un plugin: añadir una máquina nueva = un postprocesador nuevo; añadir un formato nuevo = un reader nuevo. El modelo intermedio (`PartModel`) desacopla ambos extremos.

Diseño completo: [`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md)

## Uso rápido

Sin dependencias externas para el pipeline determinista (solo Python ≥ 3.10):

```bash
# Convertir el ejemplo incluido
python3 -m cad2gcode convert examples/placa_4_agujeros.step \
    --machine doosan_dnm5700 --material aluminio -o placa.nc

# Ver las features detectadas sin generar código
python3 -m cad2gcode inspect examples/placa_4_agujeros.step
```

Con el planificador agéntico (requiere `pip install anthropic` y `ANTHROPIC_API_KEY`
o sesión `ant auth login`):

```bash
python3 -m cad2gcode convert examples/placa_4_agujeros.step \
    --machine doosan_dnm5700 --material acero --agent -o placa.nc
```

## Tests

```bash
python3 -m unittest discover -s tests -v
```

## Estado del MVP

| Capa | Estado |
|---|---|
| Reader STEP (AP203/AP214, Part 21) | ✅ detección de agujeros (superficies cilíndricas eje Z), caja envolvente |
| Modelo intermedio de features | ✅ agujeros; cajeras y contornos definidos pero sin detección |
| Planificador por reglas | ✅ centrado + taladrado (G81/G83 según profundidad), datos de corte por material |
| Planificador agéntico (Claude) | ✅ opcional, con herramientas de consulta de máquina y datos de corte |
| Postprocesador Doosan DNM 5700 | ✅ Fanuc i: G54, G43, ciclos fijos, límites de carrera verificados |
| Fresado de contornos/cajeras | 🔜 |
| Lectura de planos 2D (PDF/DXF) con cotas y tolerancias | 🔜 |
| **Agente orquestando NX CAM vía NXOpen (núcleo para superficies 3D de precisión)** | 🔜 prioridad |
| Vía experimental 3 ejes (OpenCascade + OpenCAMLib + post propio) | 🔜 |

> **Dirección del proyecto:** el cliente piloto hace mecanizado de precisión de
> superficies 3D en máquinas de 3 ejes con NX CAM. Las trayectorias de precisión
> las seguirá calculando NX; el agente automatiza la programación (estrategia,
> operaciones, herramientas, regímenes) a través de NXOpen. Ver
> [`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md) §5–6.

> ⚠️ **El código generado debe verificarse siempre** (simulación en NX/Vericut y prueba en vacío) antes de ejecutarse en máquina. El MVP no modela amarres, colisiones ni utillaje.
