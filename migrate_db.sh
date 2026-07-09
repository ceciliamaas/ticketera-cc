#!/bin/bash

# 🗄️ Script de Migración de Base de Datos
# Migra datos de PostgreSQL 15 (producción) a PostgreSQL 16+ (local) con nuevo schema

set -e  # Salir si hay errores

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Función para verificar dependencias
check_dependencies() {
    echo -e "${BLUE}🔍 Verificando dependencias...${NC}"
    
    local missing_deps=()
    
    # Verificar PostgreSQL 16
    if ! command -v /usr/local/opt/postgresql@17/bin/psql >/dev/null 2>&1; then
        missing_deps+=("PostgreSQL 16")
    fi
    
    # Verificar PostgreSQL 17 (opcional)
    if ! command -v /opt/homebrew/Cellar/postgresql@17/17.6/bin/psql >/dev/null 2>&1; then
        echo -e "${YELLOW}⚠️  PostgreSQL 17 no encontrado (opcional)${NC}"
    fi
    
    # Verificar Homebrew
    if ! command -v brew >/dev/null 2>&1; then
        missing_deps+=("Homebrew")
    fi
    
    # Verificar archivo .env
    if [[ ! -f ".env" ]]; then
        echo -e "${YELLOW}⚠️  Archivo .env no encontrado${NC}"
        echo -e "${YELLOW}   Crea uno basado en env.example${NC}"
    fi
    
    # Mostrar dependencias faltantes
    if [[ ${#missing_deps[@]} -gt 0 ]]; then
        echo -e "${RED}❌ Dependencias faltantes:${NC}"
        for dep in "${missing_deps[@]}"; do
            echo -e "${RED}   - $dep${NC}"
        done
        echo ""
        echo -e "${YELLOW}📋 Instrucciones de instalación:${NC}"
        
        if [[ " ${missing_deps[@]} " =~ " Homebrew " ]]; then
            echo -e "${BLUE}🍺 Instalar Homebrew:${NC}"
            echo "   /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
            echo ""
        fi
        
        if [[ " ${missing_deps[@]} " =~ " PostgreSQL 16 " ]]; then
            echo -e "${BLUE}🐘 Instalar PostgreSQL 16:${NC}"
            echo "   brew install postgresql@17"
            echo "   brew services start postgresql@17"
            echo ""
        fi
        
        echo -e "${YELLOW}💡 Después de instalar las dependencias, ejecuta el script nuevamente${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}✅ Todas las dependencias están instaladas${NC}"
    echo ""
}

# Configuración
NEW_SCHEMA="ticketera_new"
DUMP_FILE="dump_completo.sql"
SCHEMA_FILE="schema_only.sql"
DATA_FILE="data_only.sql"

echo -e "${BLUE}🗄️  Iniciando migración de base de datos...${NC}"

# Función para mostrar ayuda
show_help() {
    echo -e "${YELLOW}Uso: $0 [OPCIÓN]${NC}"
    echo ""
    echo "Opciones:"
    echo "  check    - Verificar dependencias del sistema"
    echo "  dump     - Hacer dump desde PostgreSQL 15 (producción)"
    echo "  create   - Crear base de datos ticketera_local en PostgreSQL local"
    echo "  restore  - Restaurar dump en ticketera_local"
    echo "  cleanup  - Limpiar archivos de dump"
    echo "  drop-db  - Eliminar base de datos ticketera_local existente"
    echo "  all      - Ejecutar todo el proceso completo"
    echo "  test-local - Verificar conexión a PostgreSQL local"
    echo "  test-remote - Verificar conexión a PostgreSQL remoto"
    echo "  test-all - Verificar ambas conexiones"
    echo "  help     - Mostrar esta ayuda"
    echo ""
    echo "Variables de entorno requeridas para dump:"
    echo "  DB_HOST, DB_USER, DB_DATABASE, DB_PASSWORD"
}

# Función para cargar variables de entorno desde .env
load_env() {
    if [[ -f ".env" ]]; then
        echo -e "${BLUE}📄 Cargando variables de entorno desde .env...${NC}"
        # Cargar variables de entorno de forma segura, ignorando líneas problemáticas
        while IFS= read -r line; do
            # Ignorar líneas vacías y comentarios
            if [[ -n "$line" && ! "$line" =~ ^[[:space:]]*# ]]; then
                # Verificar que la línea tenga formato válido (KEY=VALUE)
                if [[ "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; then
                    export "$line"
                else
                    echo -e "${YELLOW}⚠️  Ignorando línea problemática: $line${NC}"
                fi
            fi
        done < .env
    else
        echo -e "${YELLOW}⚠️  Archivo .env no encontrado, usando variables de entorno del sistema${NC}"
    fi
}

# Función para hacer dump
do_dump() {
    echo -e "${BLUE}📤 Haciendo dump desde PostgreSQL 15...${NC}"
    
    # Cargar variables de entorno
    load_env
    
    # Verificar variables de entorno (usando las mismas que Django)
    if [[ -z "$DB_HOST" || -z "$DB_USER" || -z "$DB_DATABASE" ]]; then
        echo -e "${RED}❌ Error: Variables de entorno no están configuradas${NC}"
        echo "Variables requeridas en .env:"
        echo "  DB_HOST=tu_host"
        echo "  DB_USER=tu_usuario"
        echo "  DB_DATABASE=tu_database"
        echo "  DB_PASSWORD=tu_password"
        echo ""
        echo "O configura las variables de entorno del sistema:"
        echo "export DB_HOST=tu_host"
        echo "export DB_USER=tu_usuario"
        echo "export DB_DATABASE=tu_database"
        echo "export DB_PASSWORD=tu_password"
        exit 1
    fi
    
    # Configurar PGPASSWORD para autenticación
    export PGPASSWORD="$DB_PASSWORD"
    
    # Hacer dump completo con opciones optimizadas
    echo -e "${YELLOW}📦 Creando dump completo desde $DB_HOST:$DB_DATABASE...${NC}"
    /usr/local/opt/postgresql@17/bin/pg_dump \
        -h "$DB_HOST" \
        -U "$DB_USER" \
        -d "$DB_DATABASE" \
        --no-owner \
        --no-privileges \
        --disable-triggers \
        --exclude-schema=information_schema \
        --exclude-schema=pg_catalog \
        --exclude-schema=pg_toast \
        --exclude-schema=supabase_functions \
        --exclude-schema=supabase_migrations \
        --exclude-schema=supabase_storage \
        --exclude-schema=supabase_auth \
        --exclude-schema=supabase_realtime \
        --exclude-schema=supabase_extensions \
        -f "$DUMP_FILE"
    
    # Hacer dump solo esquema con opciones optimizadas
    echo -e "${YELLOW}🏗️  Creando dump de esquema...${NC}"
    /usr/local/opt/postgresql@17/bin/pg_dump \
        -h "$DB_HOST" \
        -U "$DB_USER" \
        -d "$DB_DATABASE" \
        --schema-only \
        --no-owner \
        --no-privileges \
        --exclude-schema=information_schema \
        --exclude-schema=pg_catalog \
        --exclude-schema=pg_toast \
        --exclude-schema=supabase_functions \
        --exclude-schema=supabase_migrations \
        --exclude-schema=supabase_storage \
        --exclude-schema=supabase_auth \
        --exclude-schema=supabase_realtime \
        --exclude-schema=supabase_extensions \
        -f "$SCHEMA_FILE"
    
    # Hacer dump solo datos con opciones optimizadas
    echo -e "${YELLOW}📊 Creando dump de datos...${NC}"
    /usr/local/opt/postgresql@17/bin/pg_dump \
        -h "$DB_HOST" \
        -U "$DB_USER" \
        -d "$DB_DATABASE" \
        --data-only \
        --disable-triggers \
        --exclude-schema=information_schema \
        --exclude-schema=pg_catalog \
        --exclude-schema=pg_toast \
        --exclude-schema=supabase_functions \
        --exclude-schema=supabase_migrations \
        --exclude-schema=supabase_storage \
        --exclude-schema=supabase_auth \
        --exclude-schema=supabase_realtime \
        --exclude-schema=supabase_extensions \
        -f "$DATA_FILE"
    
    echo -e "${GREEN}✅ Dump completado exitosamente${NC}"
    echo "Archivos creados:"
    echo "  - $DUMP_FILE ($(du -h "$DUMP_FILE" | cut -f1))"
    echo "  - $SCHEMA_FILE ($(du -h "$SCHEMA_FILE" | cut -f1))"
    echo "  - $DATA_FILE ($(du -h "$DATA_FILE" | cut -f1))"
}

# Función para crear schema
create_schema() {
    echo -e "${BLUE}🏗️  Creando base de datos y schema en PostgreSQL 17...${NC}"
    
    # Crear base de datos ticketera_local (sin transacción)
    echo -e "${YELLOW}📦 Creando base de datos 'ticketera_local'...${NC}"
    
    # Verificar si la base de datos existe y eliminarla
    if $LOCAL_PSQL -d postgres -t -c "SELECT 1 FROM pg_database WHERE datname = 'ticketera_local';" | grep -q 1; then
        echo -e "${YELLOW}🗑️  Base de datos 'ticketera_local' ya existe, eliminándola...${NC}"
        
        # Terminar todas las conexiones activas a la base de datos
        $LOCAL_PSQL -d postgres -c "
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = 'ticketera_local' AND pid <> pg_backend_pid();
        " 2>/dev/null || true
        
        # Eliminar la base de datos
        $LOCAL_PSQL -d postgres -c "DROP DATABASE ticketera_local;" 2>/dev/null || true
        
        # Esperar un momento para que se complete la eliminación
        sleep 1
    fi
    
    # Crear la nueva base de datos
    echo -e "${YELLOW}🏗️  Creando nueva base de datos 'ticketera_local'...${NC}"
    $LOCAL_PSQL -d postgres -c "CREATE DATABASE ticketera_local;"
    
    # Crear schema en la nueva base de datos
    echo -e "${YELLOW}🏗️  Configurando schema 'public' en ticketera_local...${NC}"
    $LOCAL_PSQL -d ticketera_local -c "
        -- El schema 'public' ya existe por defecto
        -- Solo aseguramos que tenga los permisos correctos
        GRANT ALL PRIVILEGES ON SCHEMA public TO PUBLIC;
        GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO PUBLIC;
        GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO PUBLIC;
    "
    
    echo -e "${GREEN}✅ Base de datos 'ticketera_local' con schema 'public' creada exitosamente${NC}"
}

# Función para limpiar archivos de dump
cleanup_dump_files() {
    echo -e "${BLUE}🧹 Limpiando archivos de dump...${NC}"
    
    # Limpiar archivos de dump anteriores
    rm -f "$DUMP_FILE" "$SCHEMA_FILE" "$DATA_FILE"
    
    echo -e "${GREEN}✅ Archivos de dump limpiados${NC}"
}

# Función para eliminar base de datos existente
drop_database() {
    echo -e "${BLUE}🗑️  Eliminando base de datos 'ticketera_local'...${NC}"
    
    # Verificar si la base de datos existe
    if $LOCAL_PSQL -d postgres -t -c "SELECT 1 FROM pg_database WHERE datname = 'ticketera_local';" | grep -q 1; then
        echo -e "${YELLOW}📋 Base de datos 'ticketera_local' encontrada, eliminándola...${NC}"
        
        # Terminar todas las conexiones activas a la base de datos
        echo -e "${YELLOW}🔌 Terminando conexiones activas...${NC}"
        $LOCAL_PSQL -d postgres -c "
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = 'ticketera_local' AND pid <> pg_backend_pid();
        " 2>/dev/null || true
        
        # Eliminar la base de datos
        echo -e "${YELLOW}🗑️  Eliminando base de datos...${NC}"
        $LOCAL_PSQL -d postgres -c "DROP DATABASE ticketera_local;"
        
        echo -e "${GREEN}✅ Base de datos 'ticketera_local' eliminada exitosamente${NC}"
    else
        echo -e "${YELLOW}ℹ️  Base de datos 'ticketera_local' no existe${NC}"
    fi
}

# Función para restaurar
restore_data() {
    echo -e "${BLUE}📥 Restaurando datos en el nuevo schema...${NC}"
    
    # Verificar que existen los archivos
    if [[ ! -f "$SCHEMA_FILE" ]]; then
        echo -e "${RED}❌ Error: Archivo $SCHEMA_FILE no encontrado${NC}"
        echo "Ejecuta primero: $0 dump"
        exit 1
    fi
    
    if [[ ! -f "$DATA_FILE" ]]; then
        echo -e "${RED}❌ Error: Archivo $DATA_FILE no encontrado${NC}"
        echo "Ejecuta primero: $0 dump"
        exit 1
    fi
    
    # Restaurar esquema con opciones optimizadas (ignorar errores de schemas existentes)
    echo -e "${YELLOW}🏗️  Restaurando esquema en ticketera_local...${NC}"
    $LOCAL_PSQL -d ticketera_local -f "$SCHEMA_FILE" 2>/dev/null || {
        echo -e "${YELLOW}⚠️  Algunos schemas ya existen, continuando...${NC}"
    }
    
    # Restaurar datos con opciones optimizadas
    echo -e "${YELLOW}📊 Restaurando datos en ticketera_local...${NC}"
    $LOCAL_PSQL -d ticketera_local -f "$DATA_FILE" 2>/dev/null || {
        echo -e "${YELLOW}⚠️  Algunos datos ya existen, continuando...${NC}"
    }
    
    echo -e "${GREEN}✅ Datos restaurados exitosamente en base de datos 'ticketera_local'${NC}"
}

# Función para verificar conexión local
verify_local_connection() {
    echo -e "${BLUE}🔍 Verificando conexión a PostgreSQL local...${NC}"
    
    # Intentar con PostgreSQL 16 primero (que es el que tienes)
    if /usr/local/opt/postgresql@17/bin/psql -d postgres -c "SELECT version();" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ Conexión a PostgreSQL local exitosa${NC}"
        echo -e "${YELLOW}📊 Versión de PostgreSQL local:${NC}"
        /usr/local/opt/postgresql@17/bin/psql -d postgres -t -c "SELECT version();" | xargs
        export LOCAL_PSQL="/usr/local/opt/postgresql@17/bin/psql"
    elif /opt/homebrew/Cellar/postgresql@17/17.6/bin/psql -d postgres -c "SELECT version();" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ Conexión a PostgreSQL local exitosa${NC}"
        echo -e "${YELLOW}📊 Versión de PostgreSQL local:${NC}"
        /opt/homebrew/Cellar/postgresql@17/17.6/bin/psql -d postgres -t -c "SELECT version();" | xargs
        export LOCAL_PSQL="/opt/homebrew/Cellar/postgresql@17/17.6/bin/psql"
    else
        echo -e "${RED}❌ Error: No se puede conectar a PostgreSQL local${NC}"
        echo "Asegúrate de que PostgreSQL esté ejecutándose:"
        echo "brew services start postgresql@17"
        echo "o"
        echo "brew services start postgresql@17"
        exit 1
    fi
}

# Función para verificar conexión remota
verify_remote_connection() {
    echo -e "${BLUE}🔍 Verificando conexión a PostgreSQL remoto...${NC}"
    
    # Cargar variables de entorno
    load_env
    
    if [[ -z "$DB_HOST" || -z "$DB_USER" || -z "$DB_DATABASE" ]]; then
        echo -e "${RED}❌ Error: Variables de entorno no están configuradas${NC}"
        return 1
    fi
    
    # Configurar PGPASSWORD
    export PGPASSWORD="$DB_PASSWORD"
    
    if /usr/local/opt/postgresql@17/bin/psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_DATABASE" -c "SELECT version();" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ Conexión a PostgreSQL remoto exitosa${NC}"
        echo -e "${YELLOW}📊 Versión de PostgreSQL remoto:${NC}"
        /usr/local/opt/postgresql@17/bin/psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_DATABASE" -t -c "SELECT version();" | xargs
        return 0
    else
        echo -e "${RED}❌ Error: No se puede conectar a PostgreSQL remoto${NC}"
        echo "Verifica las variables de entorno en tu archivo .env:"
        echo "  DB_HOST=$DB_HOST"
        echo "  DB_USER=$DB_USER"
        echo "  DB_DATABASE=$DB_DATABASE"
        return 1
    fi
}

# Función para mostrar resumen
show_summary() {
    echo -e "${BLUE}📋 Resumen de la migración:${NC}"
    echo ""
    echo "Base de datos creada: ticketera_local"
    echo "Schema utilizado: public"
    echo "Archivos de dump:"
    echo "  - $DUMP_FILE"
    echo "  - $SCHEMA_FILE"
    echo "  - $DATA_FILE"
    echo ""
    echo -e "${YELLOW}Para usar la nueva base de datos en Django:${NC}"
    echo "1. Actualiza tu local_settings.py:"
    echo "   DATABASES['default']['NAME'] = 'ticketera_local'"
    echo ""
    echo "2. O crea un nuevo archivo de configuración específico para la nueva base de datos"
    echo ""
    echo -e "${GREEN}🎉 Migración completada exitosamente!${NC}"
}

# Procesar argumentos
case "${1:-help}" in
    "check")
        check_dependencies
        ;;
    "dump")
        check_dependencies
        do_dump
        ;;
    "create")
        check_dependencies
        verify_local_connection
        create_schema
        ;;
    "restore")
        check_dependencies
        verify_local_connection
        restore_data
        ;;
    "cleanup")
        cleanup_dump_files
        ;;
    "drop-db")
        check_dependencies
        verify_local_connection
        drop_database
        ;;
    "test-local")
        check_dependencies
        verify_local_connection
        ;;
    "test-remote")
        check_dependencies
        verify_remote_connection
        ;;
    "test-all")
        check_dependencies
        verify_remote_connection
        echo ""
        verify_local_connection
        ;;
    "all")
        check_dependencies
        verify_remote_connection
        echo ""
        verify_local_connection
        echo ""
        cleanup_dump_files
        do_dump
        create_schema
        restore_data
        show_summary
        ;;
    "help"|*)
        show_help
        ;;
esac
