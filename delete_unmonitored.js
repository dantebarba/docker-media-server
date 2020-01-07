// Go to Radarr and click 'settings' => 'general'.
// Open the JavaScript Console in Google Chrome (View => Developer => Javascript Console)
// Past the following in. Hit enter and away you go.

const key = document.getElementsByClassName('x-api-key')[0].value;

if (!key) {
  alert('Navigate to /settings/general and run again');
}

let ids = [];
let _movies = [];
let index = 0;

const percent = () => {
  return `[${(((index + 1) / _movies.length) * 100).toFixed(2)}%]`
}

const deleteMovie = (id) =>
  fetch(`/api/movie/${id}`, {
    method: 'DELETE',
    headers: {
      'X-Api-Key': key,
    },
  }).then(() => {
    index++;

    if (ids[index]) {
      console.log(`${percent()} Deleting ${_movies.find(m => m.id === ids[index]).title}`);
      deleteMovie(ids[index]);
    } else {
      console.log('Finished deleting movies')
      alert('It looks like all movies were deleted');
    }
  })

console.log('Fetching list of your movies, this could take a while...');
console.log('Please don\'t refresh this page until finished');

fetch('/api/movie', {
	headers: {
		'X-Api-Key': key,
	}
}).then(res => res.json()).then(movies => {
  console.log('Movie list fetched');
  _movies = movies;
  const downloaded = movies.filter(movie => !movie.monitored);
  ids = downloaded.map(movie => movie.id);

  if (ids.length) {
    console.log(`${percent()} Deleting ${movies.find(m => m.id === ids[index]).title}`);
    deleteMovie(ids[index]);
  } else {
    alert('There doesn`t seem to be any movies to delete');
  }
});