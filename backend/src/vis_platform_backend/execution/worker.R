args <- commandArgs(trailingOnly = TRUE)
job <- jsonlite::fromJSON(args[[1]], simplifyVector = FALSE)
output_dir <- job$output_dir
library(jsonlite)
dyn.load(job$sandbox_library)
invisible(.C("vis_restrict", as.character(R.home()), as.character(job$job_dir), as.character(output_dir)))
profile <- function(value) {
  scalar <- if ((is.double(value) || is.integer(value) || is.logical(value)) && length(value) == 1 && !is.na(value) && is.finite(value)) value else NULL
  kind <- if (!is.null(scalar)) "scalar" else if (is.data.frame(value)) "table" else if (is.matrix(value)) "matrix" else if (is.object(value) && !isS4(value)) "model" else "unknown"
  columns <- list()
  if (is.data.frame(value)) {
    for (name in names(value)) {
      x <- value[[name]]
      missing <- is.na(x)
      numeric <- is.numeric(x) && all(is.finite(x[!missing]))
      description <- list(name = name, data_type = if (numeric) "number" else if (is.logical(x)) "boolean" else "string",
                          missing_count = sum(missing), unique_count = length(unique(x[!missing])))
      if (numeric && any(!missing)) description$numeric <- list(minimum = min(x[!missing]), maximum = max(x[!missing]), mean = mean(x[!missing]))
      columns[[length(columns) + 1]] <- description
    }
  }
  list(kind = kind, dimensions = as.list(dim(value)), scalar = scalar, columns = columns, native_class = as.list(class(value)))
}
load_object <- function(item) {
  if (item$format == "csv") read.csv(item$path, check.names = FALSE, stringsAsFactors = FALSE)
  else if (item$format == "rds") readRDS(item$path)
  else stop("Unsupported input format")
}
tryCatch({
  if (job$mode == "check") {
    grDevices::svg(file.path(output_dir, "check.svg"))
    plot.new()
    text(0.5, 0.5, "R worker")
    grDevices::dev.off()
    response <- list(ready = TRUE)
  } else if (job$mode == "profile") {
    value <- load_object(job$input)
    for (step in job$object_path) {
      value <- if (is.numeric(step)) value[[as.integer(step) + 1L]] else if (isS4(value)) methods::slot(value, step) else value[[step]]
      if (is.null(value)) stop("The selected object is not present in this container")
    }
    values <- if (!identical(job$expand_collection, FALSE) && is.list(value) && !is.data.frame(value) && identical(class(value), "list")) value else list(data = value)
    if (!length(values) || length(values) > 100) stop("The object collection must contain 1 to 100 objects")
    if (is.null(names(values))) names(values) <- paste0("object_", seq_along(values))
    objects <- lapply(seq_along(values), function(i) {
      value <- values[[i]]
      filename <- paste0("object-", i, ".rds")
      saveRDS(value, file.path(output_dir, filename))
      csv_filename <- NULL
      if (is.data.frame(value) || is.matrix(value)) {
        csv_filename <- paste0("object-", i, ".csv")
        write.csv(value, file.path(output_dir, csv_filename), row.names = FALSE)
      }
      c(list(selector = names(values)[[i]], filename = filename, csv_filename = csv_filename), profile(value))
    })
    response <- list(objects = objects)
  } else {
    inputs <- lapply(job$inputs, load_object)
    params <- job$params
    key_values <- function(object, key, axis) {
      if (identical(axis, "rows")) rownames(object)
      else if (identical(axis, "columns")) colnames(object)
      else object[[key]]
    }
    for (relation in job$relationships) {
      left <- key_values(inputs[[relation$left_alias]], relation$left_key, relation$left_axis)
      right <- key_values(inputs[[relation$right_alias]], relation$right_key, relation$right_axis)
      if (is.null(left) || is.null(right) || anyNA(left) || anyNA(right) || any(left == "") || any(right == "")) stop("Join keys are missing or contain missing values")
      left_unique <- !anyDuplicated(left)
      right_unique <- !anyDuplicated(right)
      actual <- if (left_unique && right_unique) "one_to_one" else if (right_unique) "many_to_one" else if (left_unique) "one_to_many" else "many_to_many"
      if (relation$cardinality != "unknown" && relation$cardinality != actual) stop("Join cardinality does not match the selected inputs")
      if (actual == "many_to_many" && relation$cardinality != "many_to_many") stop("A many-to-many join requires an explicit declared relationship")
      if (any(!left %in% right)) stop("Some selected rows have no matching join key; resolve the intended treatment of unmatched rows")
    }
    set.seed(as.integer(job$random_seed))
    if (job$mode == "analyze") {
      values <- eval(parse(text = job$code), envir = list2env(list(inputs = inputs, analysis_parameters = params, params = params)))
      if (!is.list(values) || !identical(sort(names(values)), sort(unlist(job$output_names)))) stop("Analysis must return exactly the declared named outputs")
      objects <- lapply(seq_along(values), function(i) {
        value <- values[[i]]
        filename <- paste0("output-", i, ".rds")
        saveRDS(value, file.path(output_dir, filename))
        csv_filename <- NULL
        if (is.data.frame(value) || is.matrix(value)) {
          csv_filename <- paste0("output-", i, ".csv")
          write.csv(value, file.path(output_dir, csv_filename), row.names = FALSE)
        }
        c(list(selector = names(values)[[i]], filename = filename, csv_filename = csv_filename), profile(value))
      })
      response <- list(objects = objects, environment = list(R = as.character(getRversion()), jsonlite = as.character(packageVersion("jsonlite"))))
    } else if (job$mode == "render") {
      size <- job$figure_size
      if (is.null(size) || is.null(size$width) || is.null(size$height)) stop("Figure dimensions must be provided by the plot plan")
      if (!is.numeric(size$width) || !is.numeric(size$height) || !is.finite(size$width) || !is.finite(size$height) || size$width < 2 || size$width > 30 || size$height < 2 || size$height > 30) stop("Figure dimensions are outside the supported range")
      grDevices::svg(file.path(output_dir, "preview.svg"), width = size$width, height = size$height, bg = "white")
      par(mar = c(4.1, 4.1, 2.1, 1.1))
      if (isTRUE(job$contains_demo_data)) par(oma = c(1.3, 0, 0, 0))
      # Record each plotting region and its axis ranges, so a place on the image maps to data values.
      # A region is complete when the next frame starts or drawing ends.
      plot_map <- new.env()
      plot_map$panels <- list()
      plot_map$drawn <- FALSE
      record_panel <- function() {
        if (!plot_map$drawn) return(invisible(NULL))
        plot_map$panels[[length(plot_map$panels) + 1L]] <- list(
          x = graphics::grconvertX(c(0, 1), "npc", "ndc"),
          y = graphics::grconvertY(c(0, 1), "npc", "ndc"),
          usr = graphics::par("usr"),
          xlog = graphics::par("xlog"),
          ylog = graphics::par("ylog")
        )
      }
      setHook("before.plot.new", record_panel)
      setHook("plot.new", function() plot_map$drawn <- TRUE)
      eval(parse(text = job$code), envir = list2env(list(results = inputs, params = params)))
      record_panel()
      setHook("before.plot.new", NULL, "replace")
      setHook("plot.new", NULL, "replace")
      if (isTRUE(job$contains_demo_data)) mtext("Contains synthetic demonstration data", side = 1, outer = TRUE, line = 0.25, cex = 0.65, col = "#7b6d77")
      grDevices::dev.off()
      jsonlite::write_json(list(panels = plot_map$panels), file.path(output_dir, "plot-map.json"), auto_unbox = TRUE, digits = NA)
      response <- list(preview = "preview.svg", plot_map = "plot-map.json")
    } else stop("Unknown worker operation")
  }
  jsonlite::write_json(response, file.path(output_dir, "response.json"), auto_unbox = TRUE, null = "null", digits = 15)
}, error = function(error) {
  jsonlite::write_json(list(error = conditionMessage(error)), file.path(output_dir, "response.json"), auto_unbox = TRUE)
  quit(status = 1)
})
